"use strict";

// Native Web Serial only. No browser macro injection or desktop action execution.
const KINDS = [[0, "Không gán"], [1, "Phím tắt"], [10, "Giữ phím"], [3, "Chuỗi phím"],
  [4, "Khóa màn hình"], [6, "Đóng cửa sổ"]];
const HOST_KINDS = {2: "Văn bản · cần EXE", 5: "Chụp ảnh clipboard · cần EXE", 7: "Mở ứng dụng · cần EXE", 8: "Mở website · cần EXE", 9: "Chạy script · cần EXE"};
const VALUE_KINDS = new Set([1, 3, 10]);
const ORDER = ["connect", "firmware", "pins", "actions", "test", "done"];
const MODIFIERS = ["Ctrl", "Alt", "Shift", "Win"];
// ponytail: accept native firmware key names only; add normalization with firmware support.
const SPECIAL = new Set(["enter", "return", "tab", "space", "backspace", "delete", "insert", "home", "end", "page_up", "pageup", "page_down", "pagedown", "up", "down", "left", "right", "esc", "escape", "caps_lock", "print_screen", "prtsc", "plus", "media_volume_up", "media_volume_down", "media_volume_mute", "media_play_pause", ...Array.from({length: 24}, (_, i) => `f${i + 1}`)]);
const PRESETS = [["Sao chép", 1, "Ctrl+C"], ["Dán", 1, "Ctrl+V"], ["Đổi cửa sổ", 1, "Alt+Tab"], ["Chụp vùng", 1, "Win+Shift+S"], ["Phát / dừng", 1, "media_play_pause"], ["Giảm âm", 1, "media_volume_down"], ["Tăng âm", 1, "media_volume_up"], ["Giữ Alt", 10, "Alt"]];
const PIN_PRESETS = {macropad4: [3, 4, 5, 6], "ti-clicker": [7, 8, 9], "c3-nine": [0, 1, 3, 4, 5, 6, 7, 10, 20], s3: [4, 5, 6, 7], esp32: [25, 26, 27, 32]};
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const hex = (text) => [...new TextEncoder().encode(text)].map((b) => b.toString(16).padStart(2, "0")).join("").toUpperCase();
function unhex(value) {
  if (value === "-") return "";
  if (!/^(?:[0-9a-f]{2})+$/i.test(value)) throw new Error("Board trả về mã văn bản không hợp lệ.");
  return new TextDecoder("utf-8", {fatal: true}).decode(Uint8Array.from(value.match(/../g), (b) => parseInt(b, 16)));
}
function cloneActions(actions) { return Object.fromEntries(Object.entries(actions).map(([n, a]) => [n, [...a]])); }
function kindName(kind) { return KINDS.find(([id]) => id === kind)?.[1] || HOST_KINDS[kind] || `Action ${kind} · giữ nguyên`; }
function validChord(value) {
  const keys = value.split("+").map((key) => {
    const name = key.trim().toLowerCase();
    return ({control: "ctrl", windows: "win", cmd: "win"})[name] || name;
  });
  const modifiers = ["ctrl", "alt", "shift", "win"];
  if (!keys.length || keys.length > 5 || new Set(keys).size !== keys.length || keys.some((key) => !key)) return "Tổ hợp trống, lặp phím hoặc có quá nhiều phím.";
  if (keys.filter((key) => !modifiers.includes(key)).length !== 1) return "Cần đúng một phím chính; dùng Chuỗi phím cho nhiều phím liên tiếp.";
  if (keys.some((key) => !modifiers.includes(key) && !SPECIAL.has(key) && !/^[\x21-\x7e]$/.test(key))) return "Phím chưa được firmware hỗ trợ. Dùng phím nhanh bên dưới.";
  if (keys.some((key) => key.startsWith("media_")) && keys.length !== 1) return "Phím media không kết hợp với Ctrl / Alt / Shift / Win.";
  return null;
}
function validateAction(kind, value, maxValue = 512) {
  if (!Number.isInteger(kind) || kind < 0 || kind > 10 || typeof value !== "string" || value.includes("\0")) return "Action không hợp lệ.";
  if (new TextEncoder().encode(value).length > maxValue) return `Giá trị tối đa ${maxValue} byte.`;
  if (!VALUE_KINDS.has(kind)) return null;
  if (!value.trim()) return "Chưa nhập giá trị.";
  if (kind === 10) return /^(ctrl|alt|shift|win)$/i.test(value) ? null : "Chỉ chọn Ctrl, Alt, Shift hoặc Win.";
  if (kind === 1) return validChord(value);
  const steps = value.split(",").map((part) => part.trim());
  if (steps.length > 32 || steps.some((part) => !part)) return "Chuỗi cần 1–32 bước không trống, ngăn bằng dấu phẩy.";
  let wait = 0, chords = 0;
  for (const part of steps) {
    if (/^wait:/i.test(part)) {
      if (!/^wait:\d+$/i.test(part)) return "Thời gian chờ có dạng wait:300.";
      wait += Number(part.slice(5));
    } else {
      const error = validChord(part);
      if (error) return error;
      chords++;
    }
  }
  if (!chords) return "Chuỗi phải có ít nhất một phím, không chỉ chờ.";
  return wait > 3000 ? "Tổng thời gian chờ tối đa 3000 ms." : null;
}
function parseInfo(lines) {
  const get = (verb) => (lines.find((line) => line.startsWith(verb + " ")) || "").split(/\s+/).slice(1);
  const device = get("DEVICE"), limits = get("LIMITS").map(Number), cfg = get("CONFIG"), rawPins = get("PINS_OK");
  if (device.length !== 4 || device[0] !== "1" || limits.length !== 7 || cfg.length !== 4 || rawPins.length !== 1) throw new Error("Phản hồi INFO thiếu trường hoặc phiên bản giao thức chưa được hỗ trợ.");
  const usablePins = rawPins[0].split(",").map(Number), pins = cfg[1].split(",").map(Number);
  if (!limits.every(Number.isInteger) || limits[0] < 1 || limits[0] > 9 || limits[1] < 1 || limits[1] > 512 || limits[2] < 1 || limits[2] > 64 || limits[3] < 1 || limits[4] < limits[3] || limits[5] < 1 || limits[6] < limits[5]) throw new Error("Giới hạn firmware không hợp lệ.");
  if (!usablePins.length || !usablePins.every((n) => Number.isInteger(n) && n >= 0 && n < 64) || !pins.length || pins.length > limits[0] || new Set(pins).size !== pins.length || pins.some((pin) => !usablePins.includes(pin))) throw new Error("Danh sách GPIO từ board không hợp lệ.");
  const name = unhex(cfg[0]), debounceMs = Number(cfg[2]), holdMs = Number(cfg[3]);
  if (!name || /[\x00-\x1f\x7f]/.test(name) || new TextEncoder().encode(name).length > limits[2] || !Number.isInteger(debounceMs) || debounceMs < limits[3] || debounceMs > limits[4] || !Number.isInteger(holdMs) || holdMs < limits[5] || holdMs > limits[6]) throw new Error("Cấu hình trên board không hợp lệ.");
  return {chip: device[1], version: device[2], board: device[3], caps: new Set(get("CAPS")), maxButtons: limits[0], maxValue: limits[1], maxName: limits[2], debounce: limits.slice(3, 5), hold: limits.slice(5, 7), usablePins, pins, name, debounceMs, holdMs};
}
function parseActions(lines, maxButtons) {
  const actions = {};
  for (const line of lines) {
    if (!line.startsWith("ACT ")) continue;
    const fields = line.split(/\s+/), number = Number(fields[1]), kind = Number(fields[2]);
    if (fields.length !== 4 || !Number.isInteger(number) || number < 1 || number > maxButtons || !Number.isInteger(kind) || kind < 0 || kind > 255 || actions[number]) throw new Error("Dữ liệu action từ board không hợp lệ.");
    actions[number] = [kind, unhex(fields[3])];
  }
  for (let n = 1; n <= maxButtons; n++) if (!actions[n]) throw new Error(`Board thiếu dữ liệu nút ${n}.`);
  return actions;
}

let port = null, reader = null, writer = null, readTask = null, closing = false, reconnecting = false;
let info = null, draft = {}, current = "connect", selected = 1, latestVersion = null, demo = false;
let standalone = false, bleEnabled = null, modeBeforeTest = null, session = null, sequence = null;
let waiters = [], leaseTimer = null, testReady = false, recording = false, operation = false;
const completed = new Set(), visited = new Set(["connect"]), tested = new Set(), down = new Set(), modifiers = new Set();
let installerPort = null, lastBridgeAt = 0;
const HELP = {
  connect: ["USB để cấu hình", "Không cần ghép Bluetooth trước. Trang chỉ kết nối board bạn chọn trong hộp thoại của trình duyệt."],
  firmware: ["Cập nhật có kiểm soát", "Board đang dùng nên giữ dữ liệu. Erase device xóa cả GPIO, action và ghép đôi Bluetooth."],
  pins: ["GPIO là chân vật lý", "Mỗi công tắc nối một GPIO xuống GND chung. Không cần ma trận. Chọn đúng dây trước khi lưu."],
  actions: ["Lưu trên thiết bị", "Các nút trên sơ đồ là vị trí logic, không phải vị trí dây. Bấm Lưu để ghi và đọc lại cấu hình từ board."],
  test: ["Kiểm tra tín hiệu nút", "Trang chỉ hiển thị lần nhấn và nhả. Không giả lập phím Windows. Để thử Alt+Tab thực tế, hoàn tất rồi chuyển sang cửa sổ đích."],
  done: ["Dùng không cần mở web", "Phím tắt, chuỗi phím và giữ phím chạy qua Bluetooth HID. USB ở đây là cổng cấu hình, không phải USB keyboard HID."]
};
const CHECKS = [["browser", "Trình duyệt"], ["select", "Chọn cổng"], ["open", "Mở USB"], ["firmware", "Phản hồi firmware"], ["config", "Đọc cấu hình"]];
let diagnostics = [], diagnosticStart = 0, receivedBytes = 0, receivedLines = 0;
function resetDiagnostics() {
  diagnosticStart = performance.now(); receivedBytes = receivedLines = 0;
  diagnostics = CHECKS.map(([id, label]) => ({id, label, state: "pending", detail: "Chưa kiểm tra", ms: 0}));
  $("connectionChecks").replaceChildren(...diagnostics.map(({id}) => {
    const row = document.createElement("li"); row.id = `check-${id}`; return row;
  }));
  $("connectionAdvice").textContent = "Chỉ đọc thông tin khi kết nối. Không tự nạp hoặc đổi cấu hình.";
  for (const check of diagnostics) setCheck(check.id, check.state, check.detail);
}
function setCheck(id, state, detail) {
  const check = diagnostics.find((item) => item.id === id); if (!check) return;
  Object.assign(check, {state, detail, ms: Math.round(performance.now() - diagnosticStart)});
  const row = $(`check-${id}`); row.dataset.state = state;
  row.textContent = `${check.label}: ${detail}`;
}
function browserProblem() {
  if (!window.isSecureContext) return "Trang không có kết nối bảo mật. Mở bằng HTTPS hoặc localhost.";
  if (!("serial" in navigator)) return "Trình duyệt không có Web Serial. Mở bằng Chrome hoặc Edge trên máy tính.";
  const policy = document.permissionsPolicy || document.featurePolicy;
  if (policy && !policy.allowsFeature("serial")) return "Quyền Serial bị chính sách trang hoặc khung nhúng chặn. Mở trang trực tiếp trong tab mới.";
  return "";
}
function errorDetail(error) { return `${error.name || "Error"}: ${error.message || "Không có mô tả"}`; }
$("copyDiagnostics").addEventListener("click", async () => {
  const report = ["Chẩn đoán Web Serial", `Bảo mật: ${window.isSecureContext}; Web Serial: ${"serial" in navigator}`,
    ...diagnostics.map(({label, state, detail, ms}) => `${ms} ms · ${label} · ${state} · ${detail}`),
    `Nhận: ${receivedBytes} byte; ${receivedLines} dòng`, $("connectionAdvice").textContent].join("\n");
  try { await navigator.clipboard.writeText(report); say("Đã sao chép báo cáo; không chứa action, tên board hoặc địa chỉ Bluetooth.", "ok"); }
  catch {
    const field = document.createElement("textarea"); field.value = report; field.readOnly = true;
    $("diagnostics").append(field); field.focus(); field.select();
    say("Không truy cập được clipboard. Báo cáo đã được chọn; nhấn Ctrl+C để sao chép.");
    field.addEventListener("blur", () => field.remove(), {once: true});
  }
});
$("manualFirmware").addEventListener("click", () => go("firmware"));
function log(text) { const el = $("log"); el.textContent = (el.textContent + text + "\n").slice(-16000); el.scrollTop = el.scrollHeight; }
function say(text, cls = "") { $("message").textContent = text; $("message").className = cls; if (text) log(text); }
function isDirty() { return info && JSON.stringify(draft) !== JSON.stringify(info.actions); }
function updateDevice() {
  const connected = demo || !!writer;
  for (const id of ["connectionBadge", "deviceBadge"]) { $(id).textContent = demo ? "Bản mẫu" : connected ? "Đã kết nối USB" : "Chưa kết nối"; $(id).classList.toggle("online", connected); }
  $("deviceName").textContent = info?.name || "Chưa chọn board";
  $("deviceChip").textContent = info ? info.chip.toUpperCase().replace(/^ESP32(.)/, "ESP32-$1") : "—";
  $("deviceVersion").textContent = info?.version || "—";
  $("deviceCount").textContent = info ? `${info.pins.length} nút` : "—";
  $("deviceBluetooth").textContent = info ? bleEnabled === null ? "Chưa xác định" : bleEnabled ? "Đang bật" : "Đang tắt" : "—";
  $("deviceMode").textContent = info ? standalone ? "Board tự gõ" : "Tự động" : "—";
  $("deviceSave").textContent = info ? isDirty() ? "Chưa lưu" : demo ? "Dữ liệu mẫu" : "Đã đọc từ board" : "Chưa đọc";
  $("disconnect").disabled = operation || (!port && !demo);
  $("saveState").textContent = isDirty() ? "Có thay đổi chưa lưu" : demo ? "Cấu hình mẫu · chưa ghi phần cứng" : "Khớp cấu hình trên board";
  $("saveState").classList.toggle("dirty", !!isDirty());
}
async function go(name, focus = true) {
  if (operation || !ORDER.includes(name)) return;
  if (name !== "connect" && name !== "firmware" && !info) return;
  if (["test", "done"].includes(name) && isDirty()) { say("Còn action chưa lưu. Lưu hoặc hoàn tác trước khi kiểm tra/hoàn tất.", "err"); return; }
  if (name === "done" && !completed.has("test")) return;
  if (current === "test" && name !== "test") {
    try { await stopTest(); } catch (error) { say(error.message, "err"); return; }
  }
  if (!demo && writer) {
    try { if (name === "done") await releaseLease(); else { await renewLease(); startLease(); } }
    catch (error) { say(error.message, "err"); return; }
  }
  cancelRecording();
  current = name; visited.add(name);
  for (const el of document.querySelectorAll(".step")) el.hidden = el.dataset.step !== name;
  for (const button of $("stepper").querySelectorAll("button")) {
    const key = button.dataset.step;
    if (key === name) button.setAttribute("aria-current", "step"); else button.removeAttribute("aria-current");
    button.classList.toggle("complete", completed.has(key));
    button.disabled = operation || (!visited.has(key) && !completed.has(key));
  }
  $("contextTitle").textContent = HELP[name][0]; $("contextHelp").textContent = HELP[name][1];
  if (name === "firmware") renderFirmware();
  if (name === "test") await startTest();
  if (name === "done") renderDone();
  if (focus) $("title-" + name).focus({preventScroll: true});
  updateDevice();
}
async function busy(button, task) {
  if (operation) return;
  operation = true; const old = button.textContent, focused = document.activeElement;
  $("main").inert = true; $("main").setAttribute("aria-busy", "true");
  button.textContent = "Đang xử lý…"; button.setAttribute("aria-busy", "true"); button.disabled = true;
  for (const nav of $("stepper").querySelectorAll("button")) nav.disabled = true;
  $("disconnect").disabled = true;
  try { await task(); } catch (error) { say(error.message, "err"); }
  finally {
    operation = false; $("main").inert = false; $("main").removeAttribute("aria-busy");
    button.textContent = old; button.removeAttribute("aria-busy"); button.disabled = false;
    if (focused && !focused.closest("[hidden]")) focused.focus({preventScroll: true});
    else $("title-" + current).focus({preventScroll: true});
    for (const nav of $("stepper").querySelectorAll("button")) nav.disabled = !visited.has(nav.dataset.step) && !completed.has(nav.dataset.step);
    updateDevice();
  }
}
function complete(name) { completed.add(name); }
async function advance(name) { operation = false; await go(name); }
for (const button of $("stepper").querySelectorAll("button")) button.addEventListener("click", () => go(button.dataset.step));
for (const button of document.querySelectorAll("[data-back]")) button.addEventListener("click", () => go(button.dataset.back));

// Serial lifecycle: one outstanding request; renew capture while configuring so no saved macro fires.
async function openPort(p) {
  await p.open({baudRate: 115200});
  port = p;
  const vid = p.getInfo().usbVendorId;
  try {
    await p.setSignals({dataTerminalReady: vid === 0x303a, requestToSend: false});
    writer = p.writable.getWriter();
    readTask = readLoop(p);
  } catch (error) { await closePort(); throw error; }
  updateDevice();
}
async function readLoop(p) {
  const localReader = p.readable.getReader(); reader = localReader;
  const decoder = new TextDecoder(); let buffer = "";
  try {
    for (;;) {
      const {value, done} = await localReader.read(); if (done) break;
      receivedBytes += value.byteLength;
      buffer += decoder.decode(value, {stream: true});
      let index;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index).trim(); buffer = buffer.slice(index + 1);
        if (line) onLine(line);
      }
      if (buffer.length > 4096) buffer = "";
    }
  } catch (error) { if (!closing) log(`Serial: ${error.message}`); }
  finally {
    localReader.releaseLock();
    if (reader === localReader) reader = null;
    if (!closing && port === p) queueMicrotask(() => connectionLost());
  }
}
async function send(command) {
  if (!writer || !port) throw new Error("USB chưa kết nối. Quay lại bước 1.");
  if (/[\r\n]/.test(command)) throw new Error("Lệnh không hợp lệ.");
  await writer.write(new TextEncoder().encode(command + "\n"));
}
function request(command, isEnd, timeout = 2500) {
  if (waiters.length) return Promise.reject(new Error("Board đang xử lý lệnh trước, hãy thử lại."));
  return new Promise((resolve, reject) => {
    const waiter = {lines: [], isEnd, resolve, reject, timer: null};
    function fail(error) { clearTimeout(waiter.timer); waiters = waiters.filter((w) => w !== waiter); reject(error); }
    waiter.timer = setTimeout(() => fail(new Error(`Chưa nhận đủ phản hồi ${command.split(" ")[0]} sau ${timeout} ms.`)), timeout);
    waiters.push(waiter); send(command).catch(fail);
  });
}
function onLine(line) {
  receivedLines++;
  if (line.length > 1400) return;
  for (const waiter of [...waiters]) {
    waiter.lines.push(line);
    if (waiter.lines.length > 100) { clearTimeout(waiter.timer); waiters = waiters.filter((w) => w !== waiter); waiter.reject(new Error("Board trả về quá nhiều dữ liệu.")); }
    else if (waiter.isEnd(line)) { clearTimeout(waiter.timer); waiters = waiters.filter((w) => w !== waiter); waiter.resolve(waiter.lines); }
  }
  const bridge = line.match(/^BRIDGE 1 (\d+) ([01])$/);
  if (bridge) {
    const boot = Number(bridge[1]);
    if (!Number.isInteger(boot) || boot > 0xffffffff) return;
    if (session !== null && session !== boot) {
      sequence = null; testReady = false; down.clear(); tested.clear(); updateProgress();
      if (current === "test") say("Board vừa khởi động lại. Quay lại rồi mở Kiểm tra để bắt đầu lại.", "err");
    }
    session = boot; lastBridgeAt = performance.now(); standalone = bridge[2] === "1"; updateDevice();
  }
  if (line.startsWith("BLE OFF")) { bleEnabled = false; updateDevice(); }
  else if (line.startsWith("BLE ON")) { bleEnabled = true; updateDevice(); }
  const event = line.match(/^EVT (\d+) (\d+) ([1-9])(?: (PRESSED|RELEASED))?$/);
  if (event) {
    const boot = Number(event[1]), seq = Number(event[2]);
    if (boot > 0xffffffff || seq > 0xffffffff || (session !== null && boot !== session)) return;
    // Unsigned delta rejects duplicate/old packets, including sequence wrap.
    if (sequence !== null) { const delta = (seq - sequence) >>> 0; if (delta === 0 || delta >= 0x80000000) return; }
    sequence = seq;
    physicalEvent(Number(event[3]), event[4] !== "RELEASED", !!event[4] && draft[Number(event[3])]?.[0] === 10);
  }
}
async function renewLease() { if (writer) await send("APP"); }
function startLease() {
  clearInterval(leaseTimer);
  leaseTimer = setInterval(async () => {
    try {
      await renewLease();
      if (performance.now() - lastBridgeAt > 2200 && !waiters.length) await send("?");
      if (performance.now() - lastBridgeAt > 4500) throw new Error("Status timeout");
      if (current === "test" && standalone) { testReady = false; $("testSafety").textContent = "Board đã chuyển sang tự gõ. Dừng bấm nút; quay lại bước này để bật kiểm tra an toàn."; }
    } catch {
      clearInterval(leaseTimer); leaseTimer = null; testReady = false;
      $("testSafety").textContent = "Mất kết nối kiểm tra. Không tiếp tục bấm nút.";
      say("Không xác nhận được kết nối kiểm tra. Board có thể tự gõ sau 3 giây. Dừng bấm nút và kết nối lại USB.", "err");
    }
  }, 850);
}
async function releaseLease() { clearInterval(leaseTimer); leaseTimer = null; if (writer) await send("APP OFF"); }
async function closePort(release = true) {
  closing = true; clearInterval(leaseTimer); leaseTimer = null; testReady = false;
  for (const waiter of waiters) { clearTimeout(waiter.timer); waiter.reject(new Error("Kết nối USB đã đóng.")); } waiters = [];
  try { if (release && writer) await send("APP OFF"); } catch {}
  try { await reader?.cancel(); } catch {}
  try { await readTask; } catch {}
  try { writer?.releaseLock(); } catch {}
  try { await port?.close(); } catch {}
  port = reader = writer = readTask = null; session = sequence = null; closing = false; updateDevice();
}
async function connectionLost() {
  if (closing || reconnecting) return;
  const restoreWarning = modeBeforeTest !== null ? " Chưa khôi phục được chế độ trước đó; kết nối lại đúng board để kiểm tra chế độ trước khi dùng." : "";
  modeBeforeTest = null;
  await closePort(false); operation = false;
  say("Mất kết nối USB. Board có thể trở lại tự gõ phím sau 3 giây. Cắm lại rồi kết nối đúng board." + restoreWarning, "err");
  completed.clear(); visited.clear(); visited.add("connect"); await go("connect");
}
async function reopen(preferred, attempts = 12) {
  // Never silently try a different previously authorized board.
  if (!preferred) throw new Error("Chọn lại đúng board bằng nút Kết nối.");
  reconnecting = true;
  try {
    for (let i = 0; i < attempts; i++) {
      await sleep(700);
      try { await openPort(preferred); await sleep(500); await loadBoard(); return true; }
      catch { await closePort(false); }
    }
    return false;
  } finally { reconnecting = false; }
}
async function readActions() { return parseActions(await request("DUMP", (line) => line === "DUMP END"), info.maxButtons); }
async function loadBoard() {
  const previous = info;
  setCheck("firmware", "waiting", "Đã gửi INFO, đang chờ phản hồi…");
  let lines;
  try { lines = await request("INFO", (line) => line === "INFO END", 4000); }
  catch (error) {
    setCheck("firmware", "error", `${receivedBytes ? "Có dữ liệu nhưng chưa nhận đủ INFO END" : "USB mở được nhưng chưa nhận dữ liệu"}. ${errorDetail(error)}`);
    throw error;
  }
  setCheck("firmware", "ok", "Đã nhận trọn phản hồi INFO.");
  setCheck("config", "waiting", "Kiểm tra giới hạn, GPIO và action…");
  info = parseInfo(lines);
  if (previous && reconnecting && previous.chip !== info.chip) throw new Error("Board kết nối lại khác chip. Chọn lại đúng board.");
  await request("?", (line) => /^BTN\d+ GPIO\d+ (?:PRESSED|RELEASED) count=\d+$/.test(line) && Number(line.match(/^BTN(\d+)/)[1]) === info.pins.length);
  await renewLease(); startLease();
  info.actions = await readActions(); draft = cloneActions(info.actions);
  fillPins(); selected = 1; renderPad(); renderEditor(); updateDevice();
  setCheck("config", "ok", "Đã đọc và kiểm tra cấu hình, không ghi thay đổi.");
}
async function connectBoard() {
  if (operation) return;
  if (isDirty() && !window.confirm("Có thay đổi chưa lưu. Kết nối board khác sẽ bỏ các thay đổi này. Tiếp tục?")) return;
  resetDiagnostics();
  const problem = browserProblem();
  setCheck("browser", problem ? "error" : "ok", problem || "Web Serial khả dụng, trang có quyền truy cập.");
  if (problem) { $("connectionAdvice").textContent = problem; say(problem, "err"); return; }
  setCheck("select", "waiting", "Chọn đúng board trong danh sách tất cả cổng.");
  let p;
  try { p = await navigator.serial.requestPort(); }
  catch (error) {
    const cancelled = error.name === "NotFoundError";
    setCheck("select", cancelled ? "pending" : "error", cancelled ? "Chưa chọn cổng; không phải lỗi firmware." : errorDetail(error));
    $("connectionAdvice").textContent = cancelled ? "Không thấy board? Rút/cắm board rồi mở lại danh sách, tìm cổng vừa xuất hiện." : "Mở trang trực tiếp trong Chrome/Edge và kiểm tra quyền Serial của trang.";
    say(cancelled ? "Chưa chọn board. Bạn có thể mở lại danh sách cổng." : errorDetail(error), cancelled ? "" : "err"); return;
  }
  setCheck("select", "ok", "Đã chọn cổng USB.");
  await busy($("connect"), async () => {
    await stopTest(); demo = false; $("demoBanner").hidden = true; await closePort();
    info = null; bleEnabled = null; completed.clear(); visited.clear(); visited.add("connect");
    say("Đang đọc cấu hình từ board…");
    setCheck("open", "waiting", "Đang mở cổng ở 115200 baud…");
    try { await openPort(p); setCheck("open", "ok", "Đã mở USB ở 115200 baud."); await sleep(500); }
    catch (error) {
      setCheck("open", "error", errorDetail(error));
      $("connectionAdvice").textContent = "Chưa xác định cổng bị chiếm hay lỗi hệ thống. Đóng tab/ứng dụng đang dùng cổng rồi thử lại; không cần nạp firmware ở chặng này.";
      throw new Error(`Mở USB thất bại. ${errorDetail(error)}`);
    }
    try { await loadBoard(); }
    catch (error) {
      const config = diagnostics.find((item) => item.id === "config");
      if (config.state === "waiting") setCheck("config", "error", errorDetail(error));
      installerPort = p; await closePort(); info = null; updateDevice();
      $("connectionAdvice").textContent = "Chưa đủ bằng chứng firmware sai. Kiểm tra đúng cổng; nếu vừa cấp nguồn, chờ board khởi động rồi thử lại. Chỉ mở bước nạp khi biết board mới hoặc cần cập nhật.";
      say(`Dừng ở bước đọc board: ${error.message}`, "err"); return;
    }
    $("connectionAdvice").textContent = "Kết nối hoàn tất; firmware và cấu hình đã phản hồi hợp lệ.";
    installerPort = p; complete("connect"); say(`Đã đọc cấu hình ${info.name}. Chưa ghi thay đổi nào.`, "ok"); await advance("firmware");
  });
}
$("connect").addEventListener("click", connectBoard);
function renderFirmware() {
  $("firmwareReason").textContent = info ? `Board đang chạy ${info.version}. ${latestVersion && latestVersion !== info.version ? `Gói phát hành hiện có: ${latestVersion}.` : "Bạn có thể tiếp tục dùng cấu hình hiện tại."}` : "Chỉ nạp khi board mới hoặc bạn đã xác định cần cập nhật. Không nhận phản hồi USB chưa chứng minh firmware bị lỗi.";
  $("firmwareStatus").textContent = info ? `Đã nhận ${info.pins.length} nút${info.caps.has("hold_key") ? ", có hỗ trợ Giữ phím" : "; muốn dùng Giữ phím cần cập nhật firmware hỗ trợ"}.` : "Chưa xác nhận được firmware tương thích.";
  $("skipFirmware").hidden = !info; $("showInstaller").disabled = demo;
  $("installer").hidden = true;
}
$("showInstaller").addEventListener("click", () => { $("installer").hidden = !$("installer").hidden; });
$("skipFirmware").addEventListener("click", async () => {
  if (!info) return;
  if (!demo && !writer) { say("USB đã đóng để nạp firmware. Bấm Đã nạp xong hoặc quay lại Kết nối.", "err"); return; }
  complete("firmware"); await go("pins");
});
let installerReleased = false;
$("installFirmware").addEventListener("click", async (event) => {
  if (installerReleased) { installerReleased = false; return; }
  event.preventDefault(); event.stopImmediatePropagation();
  if (operation || demo) return;
  if (isDirty() && !window.confirm("Còn action chưa lưu. Bỏ bản nháp để mở trình nạp firmware?")) return;
  try {
    await stopTest(); installerPort = port || installerPort; await closePort();
    installerReleased = true; $("installFirmware").click();
  } catch (error) { say(error.message, "err"); }
}, true);
$("flashed").addEventListener("click", () => busy($("flashed"), async () => {
  say("Đang kết nối lại board vừa nạp…");
  await closePort();
  if (!await reopen(installerPort)) throw new Error("Chưa kết nối lại được board đã chọn. Quay lại Kết nối và chọn đúng cổng USB.");
  complete("firmware"); say(`Đã đọc lại board, firmware ${info.version}.`, "ok"); await advance("pins");
}));

// Physical setup.
function fillPins() {
  $("count").replaceChildren(...Array.from({length: info.maxButtons}, (_, i) => new Option(`${i + 1} nút`, i + 1)));
  $("count").value = info.pins.length; $("name").value = info.name; $("name").maxLength = info.maxName;
  $("nameLimit").textContent = `Tối đa ${info.maxName} byte; chữ có dấu dùng nhiều byte.`;
  for (const [id, bounds, value] of [["debounce", info.debounce, info.debounceMs], ["hold", info.hold, info.holdMs]]) { $(id).min = bounds[0]; $(id).max = bounds[1]; $(id).value = value; }
  $("pinPreset").value = "";
  for (const option of $("pinPreset").options) {
    const pins = PIN_PRESETS[option.value]; if (!pins) continue;
    const matchingChip = option.value === "s3" ? info.chip === "esp32s3" : option.value === "esp32" ? info.chip === "esp32" : info.chip === "esp32c3";
    option.disabled = !matchingChip || pins.length > info.maxButtons || pins.some((p) => !info.usablePins.includes(p));
  }
  renderPins(info.pins);
}
function renderPins(previous) {
  if (!info) return;
  const count = Number($("count").value), used = new Set(); $("pins").replaceChildren();
  for (let i = 0; i < count; i++) {
    const candidate = previous?.[i];
    const pin = info.usablePins.includes(candidate) && !used.has(candidate) ? candidate : info.usablePins.find((p) => !used.has(p));
    if (pin === undefined) { say("Không đủ GPIO hợp lệ cho số nút này.", "err"); return; } used.add(pin);
    const label = document.createElement("label"); label.className = "pin-field"; label.htmlFor = `pin-${i + 1}`;
    const title = document.createElement("span"); title.textContent = `Nút ${i + 1}`;
    const select = document.createElement("select"); select.id = `pin-${i + 1}`;
    info.usablePins.forEach((p) => select.add(new Option(`GPIO ${p}`, p))); select.value = pin;
    select.addEventListener("change", () => { $("pinPreset").value = ""; }); label.append(title, select); $("pins").append(label);
  }
}
$("count").addEventListener("change", () => renderPins([...$("pins").querySelectorAll("select")].map((el) => Number(el.value))));
$("pinPreset").addEventListener("change", () => { const pins = PIN_PRESETS[$("pinPreset").value]; if (pins) { $("count").value = pins.length; renderPins(pins); } });
$("savePins").addEventListener("click", () => busy($("savePins"), async () => {
  const name = $("name").value.trim(), pins = [...$("pins").querySelectorAll("select")].map((el) => Number(el.value));
  const debounceMs = Number($("debounce").value), holdMs = Number($("hold").value);
  if (!name || /[\x00-\x1f\x7f]/.test(name) || new TextEncoder().encode(name).length > info.maxName) throw new Error(`Tên Bluetooth cần 1–${info.maxName} byte, không chứa ký tự điều khiển.`);
  if (!pins.length || pins.length !== Number($("count").value) || pins.length > info.maxButtons || new Set(pins).size !== pins.length || pins.some((p) => !info.usablePins.includes(p))) throw new Error("GPIO không hợp lệ hoặc bị chọn trùng. Mỗi nút cần một chân riêng.");
  for (const [label, value, limits] of [["Chống dội", debounceMs, info.debounce], ["Thời gian giữ", holdMs, info.hold]]) if (!Number.isInteger(value) || value < limits[0] || value > limits[1]) throw new Error(`${label} cần số nguyên ${limits[0]}–${limits[1]} ms.`);
  const changed = name !== info.name || pins.join() !== info.pins.join() || debounceMs !== info.debounceMs || holdMs !== info.holdMs;
  if (changed && !demo) {
    if (isDirty()) throw new Error("Còn action chưa lưu. Quay lại Gán chức năng để lưu hoặc hoàn tác trước khi đổi phần cứng.");
    const expected = `CONFIG ${hex(name)} ${pins.join(",")} ${debounceMs} ${holdMs}`;
    const replies = await request(`CFG ${hex(name)} ${pins.join(",")} ${debounceMs} ${holdMs}`, (line) => line.startsWith("CFG "));
    if (!replies.includes("CFG OK RESTART") || !replies.includes(expected)) throw new Error("Board chưa xác nhận đúng cấu hình. Không tiếp tục; kết nối lại để đọc trạng thái.");
    say("Đã ghi phần cứng. Chờ board khởi động lại…");
    const known = port; reconnecting = true; await closePort();
    if (!await reopen(known)) throw new Error("Board đã ghi nhưng chưa kết nối lại được. Quay lại bước 1, chọn đúng board.");
    if (info.name !== name || info.pins.join() !== pins.join() || info.debounceMs !== debounceMs || info.holdMs !== holdMs) throw new Error("Cấu hình đọc sau khởi động không khớp. Kiểm tra lại board.");
  } else if (demo) {
    Object.assign(info, {name, pins, debounceMs, holdMs}); selected = Math.min(selected, pins.length); renderPad(); renderEditor();
  }
  complete("pins"); say(changed ? demo ? "Đã áp dụng phần cứng vào bản mẫu." : "Đã lưu và xác nhận phần cứng." : "Giữ nguyên phần cứng hiện tại.", "ok"); await advance("actions");
}));

// Action editor: draft values never write themselves to hardware.
function renderPad() {
  if ($("pad").children.length !== info.pins.length) {
    $("pad").replaceChildren();
    for (let n = 1; n <= info.pins.length; n++) {
      const button = document.createElement("button"); button.id = `pad-${n}`; button.className = "pad-key";
      for (const cls of ["key-top", "key-value", "key-kind"]) { const span = document.createElement("span"); span.className = cls; button.append(span); }
      button.addEventListener("click", () => { selected = n; cancelRecording(); modifiers.clear(); renderPad(); renderEditor(); });
      $("pad").append(button);
    }
  }
  for (let n = 1; n <= info.pins.length; n++) {
    const [kind, value] = draft[n] || [0, ""], button = $(`pad-${n}`);
    button.setAttribute("aria-pressed", String(selected === n)); button.setAttribute("aria-label", `Nút ${n}, ${kindName(kind)}, ${value || "không có giá trị"}`);
    button.children[0].textContent = `Nút ${n} · GPIO ${info.pins[n - 1]}`;
    button.children[1].textContent = button.children[1].title = value || kindName(kind);
    button.children[2].textContent = kindName(kind);
  }
  updateDevice();
}
function renderEditor() {
  if (!info) return;
  const [kind, value] = draft[selected] || [0, ""];
  $("editorTitle").textContent = `Nút ${selected}`; $("editorPin").textContent = `GPIO ${info.pins[selected - 1]} · ${selected}/${info.pins.length}`;
  const kinds = KINDS.filter(([id]) => id !== 10 || info.caps.has("hold_key"));
  $("actionKind").replaceChildren(...kinds.map(([id, label]) => new Option(label, id)));
  if (!kinds.some(([id]) => id === kind)) $("actionKind").add(new Option(`${kindName(kind)} · giữ nguyên`, kind));
  $("actionKind").value = kind; $("actionValue").value = value;
  $("holdValue").value = MODIFIERS.find((key) => key.toLowerCase() === value.toLowerCase()) || "Alt";
  $("copyTarget").replaceChildren(...info.pins.map((_, i) => new Option(`Nút ${i + 1}`, i + 1)));
  $("copyTarget").value = selected === 1 && info.pins.length > 1 ? 2 : 1;
  $("copyAction").disabled = info.pins.length < 2;
  updateEditor();
}
function updateEditor() {
  const [kind, value] = draft[selected] || [0, ""], host = !KINDS.some(([id]) => id === kind);
  $("actionValue").hidden = kind === 10 || !VALUE_KINDS.has(kind);
  $("actionValue").disabled = host;
  $("holdValue").hidden = kind !== 10;
  $("record").hidden = kind !== 1;
  $("quickPanel").hidden = kind !== 1 && kind !== 3;
  $("valueLabel").textContent = kind === 10 ? "Giữ đến khi nhả nút" : kind === 3 ? "Các bước, ngăn bằng dấu phẩy" : "Giá trị";
  $("actionValue").placeholder = kind === 3 ? "Ctrl+L,wait:300,Ctrl+C" : "Ctrl+C";
  const help = {0: "Nút này không thực hiện hành động.", 1: "Gõ tổ hợp, bắt từ bàn phím hoặc dùng phím nhanh. Esc hủy bắt phím; Tab vẫn dùng để di chuyển giữa các ô.", 3: "Mỗi bước là một phím hoặc tổ hợp. wait:300 chờ 300 ms; tổng chờ tối đa 3 giây. Phím nhanh nối thêm một bước.", 4: "Board gửi Win+L để khóa Windows. Chức năng phụ thuộc hệ điều hành đích.", 6: "Board gửi Alt+F4 để đóng cửa sổ đang chọn. Kiểm tra tài liệu đã lưu trước khi dùng.", 10: "Giữ nút này để giữ modifier; nhả nút để nhả phím. Ví dụ giữ Alt ở nút 1, bấm Tab ở nút 2 nhiều lần."};
  $("actionHelp").textContent = host ? "Action cần bản EXE hoặc firmware khác. Web giữ nguyên mã và dữ liệu; chỉ thay nếu bạn chọn chức năng khác." : help[kind];
  $("actionError").textContent = host ? "" : validateAction(kind, value, info.maxValue) || "";
  $("actionValue").setAttribute("aria-invalid", String(!!$("actionError").textContent));
  for (const button of $("modifiers").children) button.setAttribute("aria-pressed", String(modifiers.has(button.textContent)));
  $("editorHint").textContent = host ? "Không ghi đè action ngoài khả năng của web." : kind === 10 ? "Cần firmware có CAPS hold_key." : "Chưa ghi board cho đến khi bấm Lưu.";
}
function setAction(kind, value) {
  draft[selected] = [kind, value]; renderPad(); renderEditor();
}
$("actionKind").addEventListener("change", () => { cancelRecording(); modifiers.clear(); const kind = Number($("actionKind").value); setAction(kind, kind === 10 ? "Alt" : ""); });
$("actionValue").addEventListener("input", () => { draft[selected] = [Number($("actionKind").value), $("actionValue").value]; renderPad(); updateEditor(); });
$("holdValue").addEventListener("change", () => setAction(10, $("holdValue").value));
for (const modifier of MODIFIERS) {
  const button = document.createElement("button"); button.className = "secondary small"; button.textContent = modifier; button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", () => { modifiers.has(modifier) ? modifiers.delete(modifier) : modifiers.add(modifier); updateEditor(); }); $("modifiers").append(button);
}
for (const key of ["A", "C", "V", "X", "Z", "S", "L", "Tab", "Enter", "Backspace", "Delete", "Esc", "Space", "F4", "F5", "Print_Screen"]) {
  const button = document.createElement("button"); button.className = "secondary small"; button.textContent = key === "Print_Screen" ? "Print Screen" : key;
  button.addEventListener("click", () => {
    const chord = [...MODIFIERS.filter((m) => modifiers.has(m)), key].join("+"); modifiers.clear();
    const [kind, value] = draft[selected]; setAction(kind === 3 ? 3 : 1, kind === 3 && value.trim() ? `${value.trim()},${chord}` : chord);
  }); $("quickKeys").append(button);
}
for (const [label, kind, value] of PRESETS) {
  const button = document.createElement("button"); button.className = "secondary small"; button.textContent = label;
  button.addEventListener("click", () => { if (kind === 10 && !info.caps.has("hold_key")) return say("Firmware chưa hỗ trợ Giữ phím. Cập nhật ở bước 2.", "err"); modifiers.clear(); setAction(kind, value); }); $("presets").append(button);
}
function cancelRecording() { recording = false; $("record").textContent = "Bắt phím"; }
$("record").addEventListener("click", () => { recording = !recording; $("record").textContent = recording ? "Nhấn tổ hợp… (Esc hủy)" : "Bắt phím"; if (recording) $("record").focus(); });
document.addEventListener("keydown", (event) => {
  if (!recording) return;
  if (event.key === "Escape") { event.preventDefault(); cancelRecording(); return; }
  if (event.key === "Tab") { cancelRecording(); return; } // Preserve keyboard navigation; quick key assigns Tab.
  event.preventDefault(); event.stopPropagation();
  if (["Control", "Alt", "Shift", "Meta"].includes(event.key) || event.repeat) return;
  const names = {" ": "Space", ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right", PageUp: "Page_Up", PageDown: "Page_Down", PrintScreen: "Print_Screen", "+": "plus", ",": ""};
  const key = names[event.key] ?? (event.key.length === 1 ? event.key.toUpperCase() : event.key);
  const value = [event.ctrlKey && "Ctrl", event.altKey && "Alt", event.shiftKey && "Shift", event.metaKey && "Win", key].filter(Boolean).join("+");
  const error = validateAction(1, value, info.maxValue);
  if (error) { say(error, "err"); return; }
  cancelRecording(); modifiers.clear(); setAction(1, value);
});
window.addEventListener("blur", cancelRecording);
$("copyAction").addEventListener("click", () => { const target = Number($("copyTarget").value); draft[target] = [...draft[selected]]; renderPad(); say(`Đã sao chép nút ${selected} sang nút ${target}. Chưa ghi board.`); });
$("reloadActions").addEventListener("click", () => { if (isDirty() && !window.confirm("Bỏ các action chưa lưu và trở lại cấu hình đã đọc từ board?")) return; draft = cloneActions(info.actions); modifiers.clear(); renderPad(); renderEditor(); say("Đã hoàn tác các action chưa lưu."); });
$("exportProfile").addEventListener("click", () => {
  const actions = Array.from({length: info.pins.length}, (_, i) => ({button: i + 1, kind: draft[i + 1][0], value: draft[i + 1][1]}));
  const blob = new Blob([JSON.stringify({format: "timewo-board-actions", version: 1, actions}, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob), anchor = document.createElement("a"); anchor.href = url; anchor.download = "macropad-actions.json"; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  say("Đã xuất bản nháp action. File không chứa GPIO, ghép đôi hay dữ liệu firmware.");
});
$("importProfile").addEventListener("click", () => $("profileFile").click());
function validateImport(raw) {
  if (raw?.format !== "timewo-board-actions" || raw.version !== 1 || !Array.isArray(raw.actions) || raw.actions.length < 1 || raw.actions.length > info.pins.length) throw new Error("File không đúng định dạng action web hoặc có nhiều nút hơn board.");
  const next = cloneActions(draft), seen = new Set();
  for (const action of raw.actions) {
    if (!action || !Number.isInteger(action.button) || action.button < 1 || action.button > info.pins.length || seen.has(action.button) || !Number.isInteger(action.kind) || action.kind < 0 || action.kind > 10) throw new Error("File có nút trùng/sai hoặc mã action không hỗ trợ.");
    const unchanged = JSON.stringify(info.actions[action.button]) === JSON.stringify([action.kind, action.value]);
    if (!unchanged) {
      if (action.kind === 10 && !info.caps.has("hold_key")) throw new Error("Firmware chưa hỗ trợ Giữ phím.");
      const error = validateAction(action.kind, action.value, info.maxValue); if (error) throw new Error(`Nút ${action.button}: ${error}`);
    }
    seen.add(action.button); next[action.button] = [action.kind, action.value];
  }
  return next;
}
$("profileFile").addEventListener("change", async () => {
  try {
    const file = $("profileFile").files[0]; if (!file) return;
    if (file.size > 32000) throw new Error("File quá lớn. Chọn JSON action nhỏ hơn 32 KB.");
    const next = validateImport(JSON.parse(await file.text()));
    if (isDirty() && !window.confirm("Nhập file sẽ thay các nút có trong file ở bản nháp. Tiếp tục?")) return;
    draft = next; renderPad(); renderEditor(); say("Đã nhập vào bản nháp. Kiểm tra từng nút trước khi Lưu.");
  } catch (error) { say(error.message, "err"); } finally { $("profileFile").value = ""; }
});
$("saveActions").addEventListener("click", () => busy($("saveActions"), async () => {
  cancelRecording();
  for (let n = 1; n <= info.pins.length; n++) {
    const [kind, value] = draft[n];
    if (JSON.stringify(draft[n]) === JSON.stringify(info.actions[n])) continue;
    const error = validateAction(kind, value, info.maxValue);
    if (error) { selected = n; renderPad(); renderEditor(); $("actionValue").focus(); throw new Error(`Nút ${n}: ${error}`); }
    if (kind === 10 && !info.caps.has("hold_key")) throw new Error(`Nút ${n}: firmware chưa hỗ trợ Giữ phím.`);
  }
  if (!demo) {
    say(isDirty() ? "Đang lưu và đọc lại từng action…" : "Không có thay đổi. Đang xác nhận lại cấu hình board…");
    await renewLease();
    const before = await readActions();
    if (JSON.stringify(before) !== JSON.stringify(info.actions)) throw new Error("Cấu hình board đã đổi ngoài trang này. Kết nối lại và đọc cấu hình trước khi lưu.");
    const changed = isDirty();
    if (changed) {
      // Stage full snapshot, including hidden/desktop entries, to replace abandoned staging.
      for (let n = 1; n <= info.maxButtons; n++) {
        $("saveActions").textContent = `Đang lưu nút ${n}/${info.maxButtons}…`;
        const [kind, value] = draft[n];
        const replies = await request(`SYNC ${n} ${kind} ${value ? hex(value) : "-"}`, (line) => line.startsWith("SYNC ACTION"));
        if (!replies.at(-1).endsWith("OK")) throw new Error(`Board từ chối nút ${n}. Chưa xác nhận lưu.`);
      }
      const reply = await request("SYNC_COMMIT", (line) => line.startsWith("SYNC COMMIT"));
      if (reply.at(-1) !== "SYNC COMMIT OK") throw new Error("Board chưa xác nhận ghi cấu hình.");
    }
    const actual = changed ? await readActions() : before;
    for (let n = 1; n <= info.maxButtons; n++) if (JSON.stringify(actual[n]) !== JSON.stringify(draft[n])) throw new Error(`Nút ${n} đọc lại không khớp. Chưa thể xác nhận đã lưu.`);
    info.actions = actual;
  } else info.actions = cloneActions(draft);
  draft = cloneActions(info.actions); complete("actions"); renderPad();
  say(demo ? "Đã áp dụng vào bản mẫu, không ghi phần cứng." : "Đã lưu và đọc lại khớp toàn bộ action.", "ok"); await advance("test");
}));

// Test receives physical edges only. No key injection, including in demo mode.
function buildTestKeys() {
  tested.clear(); down.clear(); $("keys").replaceChildren();
  for (let n = 1; n <= info.pins.length; n++) {
    const key = document.createElement(demo ? "button" : "div"); key.id = `test-key-${n}`; key.className = "pad-key test-key";
    const top = document.createElement("span"); top.className = "key-top"; top.textContent = `Nút ${n} · GPIO ${info.pins[n - 1]}`;
    const value = document.createElement("span"); value.className = "key-value"; value.textContent = draft[n]?.[1] || kindName(draft[n]?.[0] || 0);
    const status = document.createElement("span"); status.className = "key-kind"; status.textContent = "Chưa nhận tín hiệu";
    key.append(top, value, status);
    if (demo) key.addEventListener("click", () => { physicalEvent(n, true, true); setTimeout(() => physicalEvent(n, false, true), 180); });
    $("keys").append(key);
  }
  $("lastEvent").textContent = demo ? "Bản mẫu: bấm vào ô để mô phỏng tín hiệu, không phải test phần cứng." : "Chưa có lần nhấn nào.";
  updateProgress();
}
async function startTest() {
  buildTestKeys(); testReady = false;
  $("testWarning").hidden = true; $("enableSafeTest").hidden = true;
  if (demo) { testReady = true; $("testSafety").textContent = "Bản mẫu: click các nút bên dưới để xem trạng thái. Không có phần cứng được kiểm tra."; return; }
  try { await request("?", (line) => line.startsWith("BRIDGE 1 ")); }
  catch (error) { $("testSafety").textContent = "Chưa xác nhận được chế độ board. Không bấm nút."; say(error.message, "err"); return; }
  if (standalone) {
    $("testSafety").textContent = "Chưa thể kiểm tra an toàn: board đang ở chế độ luôn tự gõ.";
    $("testWarning").textContent = "Đừng bấm nút lúc này: board có thể gửi phím vào cửa sổ khác. Chuyển tạm sang Tự động để web nhận tín hiệu; khi rời bước này sẽ khôi phục chế độ cũ.";
    $("testWarning").hidden = false; $("enableSafeTest").hidden = false; return;
  }
  try { await renewLease(); startLease(); testReady = true; $("testSafety").textContent = "Chế độ kiểm tra đã bật. Web nhận tín hiệu, không gửi phím vào Windows khi kết nối còn hoạt động."; }
  catch (error) { $("testSafety").textContent = "Chưa bật được kiểm tra. Không bấm nút."; say(error.message, "err"); }
}
$("enableSafeTest").addEventListener("click", () => busy($("enableSafeTest"), async () => {
  modeBeforeTest = true; await renewLease(); startLease();
  await request("MODE APP", (line) => line.startsWith("BRIDGE 1 "));
  if (standalone) throw new Error("Board chưa xác nhận chế độ Tự động.");
  await startTest(); updateDevice();
}));
async function stopTest() {
  testReady = false;
  if (modeBeforeTest !== null && !demo && writer) {
    await request(modeBeforeTest ? "MODE HID" : "MODE APP", (line) => line.startsWith("BRIDGE 1 "));
    if (standalone !== modeBeforeTest) throw new Error("Chưa xác nhận khôi phục chế độ board. Đừng ngắt USB; thử lại.");
    modeBeforeTest = null;
  }
}
function physicalEvent(n, pressed, stateful = false) {
  if (current !== "test" || !testReady || !info || n > info.pins.length) return;
  const el = $(`test-key-${n}`); if (!el) return;
  if (pressed) { tested.add(n); if (stateful) down.add(n); } else down.delete(n);
  el.classList.toggle("tested", tested.has(n)); el.classList.toggle("down", down.has(n));
  el.querySelector(".key-kind").textContent = down.has(n) ? "Đang giữ" : !stateful && pressed ? "Đã nhận lần nhấn" : "Đã nhận · đã nhả";
  el.classList.add("hit"); setTimeout(() => el.classList.remove("hit"), 180);
  $("lastEvent").textContent = `${demo ? "Mô phỏng · " : ""}Nút ${n} · ${pressed ? "nhấn" : "nhả"} · ${new Date().toLocaleTimeString("vi-VN")}`;
  updateProgress();
}
function updateProgress() {
  const total = info?.pins.length || 0, all = tested.size === total;
  $("testProgress").textContent = all ? `Đã nhận đủ ${total}/${total} nút${demo ? " mô phỏng" : ""}.` : `Đã nhận ${tested.size}/${total} nút${demo ? " mô phỏng" : ""}.`;
  $("testProgress").className = all ? "ok" : "muted";
  $("testBar").setAttribute("aria-valuemax", total); $("testBar").setAttribute("aria-valuenow", tested.size);
  $("testFill").style.width = `${total ? tested.size / total * 100 : 0}%`;
}
$("resetTest").addEventListener("click", buildTestKeys);
$("finish").addEventListener("click", () => busy($("finish"), async () => {
  if (down.size) throw new Error("Nhả các nút đang giữ trước khi hoàn tất.");
  if (tested.size < info.pins.length && !window.confirm(`Mới nhận ${tested.size}/${info.pins.length} nút. Hoàn tất dù chưa kiểm tra hết?`)) return;
  await stopTest(); if (!demo) await releaseLease(); complete("test"); say(""); await advance("done");
}));
function renderDone() {
  $("doneSummary").textContent = demo ? "Đã hoàn tất luồng minh họa. Chưa lưu hay kiểm tra thiết bị thật." : "Cấu hình đã lưu và đọc lại từ board. Đóng trang vẫn dùng được những chức năng chạy trên board.";
  $("doneName").textContent = info.name;
  $("doneHoldNote").textContent = `Giữ nút cuối ${(info.holdMs / 1000).toLocaleString("vi-VN")} giây để bật/tắt Bluetooth, trừ khi nút đó gán Giữ phím.`;
  $("pairHint").hidden = info.pins.length < 9; $("pairSeconds").textContent = (info.holdMs / 1000).toLocaleString("vi-VN");
  $("doneTestNote").textContent = demo ? "Đây là bản mẫu. Chưa nạp, lưu hay kiểm tra board thật." : bleEnabled === false ? "Bluetooth đang tắt. Giữ nút cuối để bật nếu nút cuối không gán Giữ phím; nếu có, bật bằng bản EXE hoặc đổi action trước." : `Đã kiểm tra tín hiệu ${tested.size}/${info.pins.length} nút. Để kiểm tra hành động thực tế, chuyển sang ứng dụng đích rồi bấm board.`;
}
$("again").addEventListener("click", async () => { if (!demo && writer) { await renewLease(); startLease(); } await go("actions"); });
async function disconnect() {
  if (operation) return;
  if (isDirty() && !window.confirm("Có action chưa lưu. Ngắt kết nối và bỏ bản nháp?")) return;
  try { await stopTest(); } catch (error) { say(error.message, "err"); return; }
  await closePort(); demo = false; info = null; draft = {}; $("demoBanner").hidden = true;
  completed.clear(); visited.clear(); visited.add("connect"); await go("connect"); say("Đã ngắt kết nối. Cấu hình đã lưu trên board không thay đổi.");
}
$("disconnect").addEventListener("click", disconnect); $("disconnectDone").addEventListener("click", disconnect);
function startDemo() {
  if (port || operation) return;
  demo = true; standalone = false; bleEnabled = true;
  info = {chip: "esp32c3", version: "mẫu", board: "demo", caps: new Set(["hold_key"]), maxButtons: 9, maxValue: 512, maxName: 15, debounce: [5, 200], hold: [500, 10000], usablePins: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 21], name: "Macropad mẫu", pins: [3, 4, 5, 6], debounceMs: 30, holdMs: 2500,
    actions: {1: [1, "Ctrl+C"], 2: [1, "Ctrl+V"], 3: [10, "Alt"], 4: [1, "Tab"], 5: [0, ""], 6: [0, ""], 7: [0, ""], 8: [0, ""], 9: [0, ""]}};
  draft = cloneActions(info.actions); selected = 1; completed.clear(); complete("connect"); complete("firmware"); complete("pins");
  for (const key of ["connect", "firmware", "pins", "actions"]) visited.add(key);
  $("demoBanner").hidden = false; fillPins(); renderPad(); renderEditor(); say("Bản mẫu có dữ liệu minh họa. Không có board nào được kết nối."); go("actions");
}
$("demo").addEventListener("click", startDemo); $("unsupportedDemo").addEventListener("click", startDemo); $("exitDemo").addEventListener("click", disconnect);
$("theme").addEventListener("change", () => { const theme = $("theme").value; if (theme === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme; try { localStorage.setItem("macropad-theme", theme); } catch {} });
try { const theme = localStorage.getItem("macropad-theme"); if (["light", "dark"].includes(theme)) { $("theme").value = theme; document.documentElement.dataset.theme = theme; } } catch {}
window.addEventListener("beforeunload", (event) => { if (isDirty() || modeBeforeTest !== null) { event.preventDefault(); event.returnValue = ""; } });
navigator.serial?.addEventListener("disconnect", (event) => { if (event.target === port && !reconnecting && !closing) connectionLost(); });
resetDiagnostics();
const initialProblem = browserProblem();
setCheck("browser", initialProblem ? "error" : "ok", initialProblem || "Web Serial khả dụng.");
if (initialProblem) { $("unsupported").hidden = false; $("connect").disabled = true; $("connectionAdvice").textContent = initialProblem; }
fetch("firmware/web-manifest.json").then((r) => r.ok ? r.json() : null).then((manifest) => { latestVersion = typeof manifest?.version === "string" ? manifest.version : null; }).catch(() => {});
go("connect", false);

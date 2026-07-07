/*
 * AromaDiffuser — sACN (E1.31) OR OSC -> pump trigger for a theatre aroma diffuser.
 *
 * An ESP32-C3 joins the show network, receives cues over the network and switches
 * the diffuser's air pump on/off through a relay. The original diffuser controller
 * (the AXTEK MCU board) is bypassed entirely — we reuse only its 12 V PSU and pump.
 *
 * Two control protocols, picked on the config page:
 *
 *   sACN (E1.31)   continuous DMX stream. Watch one universe/channel; pump fires
 *                  when the channel value >= threshold. "No packets for 2.5 s = OFF"
 *                  failsafe (the stream stopping means something is wrong).
 *
 *   OSC            event messages (e.g. from QLab). One configurable address; the
 *                  argument decides on/off ( >=0.5 / non-zero = ON, bare msg = ON ).
 *                  Events are fire-and-forget, so there is NO stream-timeout
 *                  failsafe — the pump holds its last command. Stuck-on is caught
 *                  by the Max-ON watchdog and by "lost WiFi = OFF".
 *
 * Safety, both protocols: losing WiFi forces the pump OFF, and an optional Max-ON
 * watchdog force-stops scent after N seconds.
 *
 * WiFi is set from a captive-portal web page (WiFiManager) at first boot; hold
 * BOOT (GPIO9) at power-up to reopen it. Protocol/universe/channel/hostname etc.
 * are also editable live at http://<hostname>.local/ (saves to NVS + reboots).
 *
 * Target: ESP32-C3 Super Mini (WiFi only).   PlatformIO env: c3
 */

#include <WiFiManager.h>          // WiFi + the config-portal web server
#include <Preferences.h>
#include <WiFiUdp.h>
#include <OSCMessage.h>           // CNMAT/OSC
#include <ESPAsyncWebServer.h>    // always-on status page
#include <ESPmDNS.h>
#include <string.h>

// ─── Hardware pins ───────────────────────────────────────────────────────────
static const uint8_t  PUMP_PIN    = 10;     // -> relay IN. 10k pulldown to GND = boot-safe OFF
static const uint8_t  LED_PIN     = 8;      // onboard status LED
static const uint8_t  BTN_PIN    = 9;      // BOOT button — hold at power-up to open config
static const uint8_t  LED_ON      = HIGH;   // active-LOW Super Mini clone? set this to LOW
static const bool     RELAY_ON    = HIGH;   // HIGH-level-trigger relay: HIGH energises = pump on
static const uint32_t FAILSAFE_MS = 2500;   // sACN network-data-loss window (E1.31)

// ─── Runtime config (loaded from NVS, set via the portal) ────────────────────
bool     useOsc    = false;        // false = sACN, true = OSC
uint16_t universe  = 1;            // [sACN] universe patched on the desk
uint16_t channel   = 1;            // [sACN] DMX slot 1..512 that fires the scent
uint8_t  threshold = 128;          // [sACN] value at/above which the pump fires
String   oscAddr   = "/aroma";     // [OSC] address to listen on
uint16_t oscPort   = 8000;         // [OSC] UDP port to listen on
uint16_t maxOn     = 0;            // Max ON seconds, 0 = unlimited (stuck-on watchdog)
String   hostname  = "aroma";      // mDNS name -> http://<hostname>.local

static const uint16_t SACN_PORT = 5568;   // E1.31

Preferences    prefs;
WiFiManager    wm;
WiFiUDP        udp;                // shared transport (sACN multicast OR OSC — one at a time)
AsyncWebServer server(80);        // always-on status page
uint8_t        pkt[638];          // one E1.31 packet (126-byte header + up to 512 slots)
uint32_t       lastPacket = 0;
uint32_t       pumpSince  = 0;
uint32_t       puffUntil  = 0;     // web Test button: force pump on until this millis()
uint32_t       rebootAt   = 0;     // deferred restart after a config save (0 = none)
bool           pumpOn     = false;

inline void led(bool on) { digitalWrite(LED_PIN, on ? LED_ON : !LED_ON); }

void setPump(bool on) {
  if (on == pumpOn) return;        // edge-only: log + write on change
  pumpOn = on;
  if (on) pumpSince = millis();
  digitalWrite(PUMP_PIN, on ? RELAY_ON : !RELAY_ON);
  Serial.printf("[pump] %s\n", on ? "ON" : "off");
}

// ─── Config persistence ──────────────────────────────────────────────────────
void loadCfg() {
  prefs.begin("aroma", true);
  useOsc    = prefs.getBool  ("osc", false);
  universe  = prefs.getUShort("uni", 1);
  channel   = prefs.getUShort("ch",  1);
  threshold = prefs.getUChar ("thr", 128);
  oscAddr   = prefs.getString("oaddr", "/aroma");
  oscPort   = prefs.getUShort("oport", 8000);
  maxOn     = prefs.getUShort("maxon", 0);
  hostname  = prefs.getString("host", "aroma");
  prefs.end();
}

void saveCfg() {
  prefs.begin("aroma", false);
  prefs.putBool  ("osc",   useOsc);
  prefs.putUShort("uni",   universe);
  prefs.putUShort("ch",    channel);
  prefs.putUChar ("thr",   threshold);
  prefs.putString("oaddr", oscAddr);
  prefs.putUShort("oport", oscPort);
  prefs.putUShort("maxon", maxOn);
  prefs.putString("host",  hostname);
  prefs.end();
}

// Open the WiFiManager portal (forced if BOOT was held), then persist whatever the
// form returned. Blocks while the portal is up. Reboots if no WiFi results.
void configure(bool force) {
  char su[7], sc[6], st[6], sp[7], sm[7];
  snprintf(su, sizeof su, "%u", universe);
  snprintf(sc, sizeof sc, "%u", channel);
  snprintf(st, sizeof st, "%u", threshold);
  snprintf(sp, sizeof sp, "%u", oscPort);
  snprintf(sm, sizeof sm, "%u", maxOn);
  WiFiManagerParameter p_proto("proto", "Protocol: sacn or osc", useOsc ? "osc" : "sacn", 5);
  WiFiManagerParameter p_uni  ("uni",   "[sACN] universe (1-63999)", su, 6);
  WiFiManagerParameter p_ch   ("ch",    "[sACN] channel (1-512)",    sc, 4);
  WiFiManagerParameter p_thr  ("thr",   "[sACN] threshold (1-255)",  st, 4);
  WiFiManagerParameter p_addr ("oaddr", "[OSC] address",  oscAddr.c_str(), 31);
  WiFiManagerParameter p_port ("oport", "[OSC] UDP port", sp, 6);
  WiFiManagerParameter p_max  ("maxon", "Max ON seconds (0 = unlimited)", sm, 5);
  for (auto p : {&p_proto, &p_uni, &p_ch, &p_thr, &p_addr, &p_port, &p_max})
    wm.addParameter(p);
  wm.setConfigPortalTimeout(180);  // give up the portal after 3 min, carry on
  // C3 softAP in modem-sleep drops association frames -> macOS "association failed".
  // Kill power-save the moment the portal AP comes up.
  wm.setAPCallback([](WiFiManager*){ WiFi.setSleep(WIFI_PS_NONE); });

  Serial.println("Config AP: \"AromaDiffuser-setup\"  pass: aroma1234  (browse to 192.168.4.1)");
  bool ok = force ? wm.startConfigPortal("AromaDiffuser-setup", "aroma1234")
                  : wm.autoConnect("AromaDiffuser-setup", "aroma1234");

  // getValue() == the submitted form value, or our defaults if the portal never
  // opened — so this is a safe no-op re-save when WiFi connected straight away.
  useOsc    = (strcasecmp(p_proto.getValue(), "osc") == 0);
  universe  = constrain(atoi(p_uni.getValue()),  1, 63999);
  channel   = constrain(atoi(p_ch.getValue()),   1, 512);
  threshold = constrain(atoi(p_thr.getValue()),  1, 255);
  oscAddr   = p_addr.getValue();
  if (oscAddr.isEmpty() || oscAddr[0] != '/') oscAddr = "/aroma";
  oscPort   = constrain(atoi(p_port.getValue()), 1, 65535);
  maxOn     = constrain(atoi(p_max.getValue()),  0, 65535);
  saveCfg();

  if (!ok) { Serial.println("No WiFi — rebooting"); ESP.restart(); }
}

// ─── OSC receive ─────────────────────────────────────────────────────────────
void onOsc(OSCMessage &m) {
  bool on;
  if      (m.size() == 0)  on = true;                       // bare message = ON
  else if (m.isFloat(0))   on = m.getFloat(0) >= 0.5f;
  else if (m.isInt(0))     on = m.getInt(0) != 0;
  else                     on = true;
  setPump(on);
}

void pollOsc() {
  int size = udp.parsePacket();
  if (size <= 0) return;
  OSCMessage msg;
  while (size--) msg.fill(udp.read());
  if (!msg.hasError()) msg.dispatch(oscAddr.c_str(), onOsc);
}

// ─── sACN / E1.31 receive ────────────────────────────────────────────────────
// We only need one slot from one universe, so we parse the packet directly rather
// than pull in a library. (The usual ESPAsyncE131 lib uses Xtensa asm and will not
// build on the RISC-V C3.) sACN is multicast to 239.255.<uni-hi>.<uni-lo>:5568.
void sacnBegin(uint16_t uni) {
  udp.beginMulticast(IPAddress(239, 255, (uni >> 8) & 0xFF, uni & 0xFF), SACN_PORT);
}

void pollSacn() {
  int len = udp.parsePacket();
  if (len < 126) return;                                  // shorter than an E1.31 header
  int n = udp.read(pkt, sizeof pkt);
  if (n < 126) return;
  if (memcmp(pkt + 4, "ASC-E1.17", 9) != 0) return;       // ACN packet identifier
  uint16_t pktUni = (pkt[113] << 8) | pkt[114];
  if (pktUni != universe) return;                         // not our universe
  if (pkt[125] != 0x00) return;                           // not a 0-start-code DMX frame
  int idx = 125 + channel;                                // slot N lives at byte 125+N
  if (idx >= n) return;                                   // packet doesn't reach our slot
  lastPacket = millis();
  setPump(pkt[idx] >= threshold);
}

// ─── Always-on status page ───────────────────────────────────────────────────
static const char PAGE[] = R"HTML(<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>AromaDiffuser</title>
<style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;text-align:center;margin:0;padding:1.5rem}
#dot{font-size:4rem;line-height:1}.on{color:#2dd4bf}.off{color:#444}
table{margin:1rem auto;border-collapse:collapse}td{padding:.2rem .8rem;text-align:left}
button{font-size:1.3rem;padding:1rem 2rem;margin-top:1rem;border:0;border-radius:.6rem;background:#2dd4bf;color:#012}
button:active{transform:scale(.97)}
form{max-width:340px;margin:1.5rem auto 0;text-align:left}
label{display:block;margin:.6rem 0 .1rem;font-size:.9rem;color:#aaa}
input,select{width:100%;padding:.5rem;box-sizing:border-box;background:#222;color:#eee;border:1px solid #444;border-radius:.4rem;font-size:1rem}
hr{border:0;border-top:1px solid #333;margin:1.5rem 0}</style></head><body>
<h1>AromaDiffuser</h1><div id=dot class=off>&#9679;</div><div id=state>&mdash;</div>
<table id=info></table><button onclick="fetch('/test')">Test puff (2s)</button>
<hr><h2>Config</h2>
<form id=cfg onsubmit="return save(event)">
<label>Hostname (.local)</label><input name=host maxlength=31>
<label>Protocol</label><select name=proto><option value=sacn>sACN (E1.31)</option><option value=osc>OSC</option></select>
<label>[sACN] Universe (1-63999)</label><input name=universe type=number min=1 max=63999>
<label>[sACN] Channel (1-512)</label><input name=channel type=number min=1 max=512>
<label>[sACN] Threshold (1-255)</label><input name=threshold type=number min=1 max=255>
<label>[OSC] Address</label><input name=addr maxlength=31>
<label>[OSC] UDP port</label><input name=port type=number min=1 max=65535>
<label>Max ON seconds (0 = unlimited)</label><input name=maxon type=number min=0 max=65535>
<button>Save &amp; reboot</button></form>
<script>async function tick(){try{
const s=await(await fetch('/status.json')).json(),on=s.pump==1;
const d=document.getElementById('dot');d.className=on?'on':'off';
document.getElementById('state').textContent=on?'SCENT ON':'idle';
let r=[['Protocol',s.proto],['IP',s.ip],['Signal',s.rssi+' dBm']];
if(s.proto=='osc')r.push(['OSC address',s.addr],['OSC port',s.port]);
else r.push(['Universe',s.universe],['Channel',s.channel],['Threshold',s.threshold]);
r.push(['Max ON',s.maxon?s.maxon+' s':'unlimited']);
document.getElementById('info').innerHTML=r.map(x=>`<tr><td>${x[0]}</td><td><b>${x[1]}</b></td></tr>`).join('');
}catch(e){document.getElementById('state').textContent='disconnected';}}
async function fill(){const s=await(await fetch('/status.json')).json(),f=document.cfg;
for(const k of['host','proto','universe','channel','threshold','addr','port','maxon'])f[k].value=s[k];}
async function save(e){e.preventDefault();
await fetch('/save',{method:'POST',body:new FormData(document.cfg)});
document.getElementById('state').textContent='saved — rebooting…';return false;}
fill();setInterval(tick,1000);tick();</script></body></html>)HTML";

void handleStatus(AsyncWebServerRequest *req) {
  // All fields always present so the config form can prefill regardless of proto.
  String j = "{";
  j += "\"proto\":\"" + String(useOsc ? "osc" : "sacn") + "\",";
  j += "\"pump\":"  + String(pumpOn ? 1 : 0) + ",";
  j += "\"ip\":\""  + WiFi.localIP().toString() + "\",";
  j += "\"rssi\":"  + String(WiFi.RSSI()) + ",";
  j += "\"host\":\"" + hostname + "\",";
  j += "\"universe\":" + String(universe) + ",\"channel\":" + String(channel) +
       ",\"threshold\":" + String(threshold) + ",";
  j += "\"addr\":\"" + oscAddr + "\",\"port\":" + String(oscPort) + ",";
  j += "\"maxon\":" + String(maxOn) + "}";
  req->send(200, "application/json", j);
}

// POST /save: persist the config form, then reboot to apply (re-inits listeners + mDNS).
void handleSave(AsyncWebServerRequest *r) {
  auto arg = [&](const char *k, const String &d) -> String {
    return r->hasParam(k, true) ? r->getParam(k, true)->value() : d;
  };
  useOsc    = arg("proto", "sacn") == "osc";
  universe  = constrain(arg("universe", "1").toInt(),  1, 63999);
  channel   = constrain(arg("channel", "1").toInt(),   1, 512);
  threshold = constrain(arg("threshold", "128").toInt(), 1, 255);
  oscAddr   = arg("addr", "/aroma");
  if (oscAddr.isEmpty() || oscAddr[0] != '/') oscAddr = "/aroma";
  oscPort   = constrain(arg("port", "8000").toInt(), 1, 65535);
  maxOn     = constrain(arg("maxon", "0").toInt(),   0, 65535);
  hostname  = arg("host", "aroma");
  if (hostname.isEmpty()) hostname = "aroma";
  saveCfg();
  r->send(200, "text/plain", "saved, rebooting");
  rebootAt = millis() + 400;                        // let the response flush first
}

void startWeb() {
  MDNS.begin(hostname.c_str());
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *r) { r->send(200, "text/html", PAGE); });
  server.on("/status.json", HTTP_GET, handleStatus);
  server.on("/save", HTTP_POST, handleSave);
  server.on("/test", HTTP_GET, [](AsyncWebServerRequest *r) {
    puffUntil = millis() + 2000;                  // 2 s test puff
    r->send(200, "text/plain", "ok");
  });
  server.begin();
  MDNS.addService("http", "tcp", 80);
  Serial.printf("Web UI: http://%s.local\n", hostname.c_str());
}

void setup() {
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, !RELAY_ON);   // OFF before anything else
  pinMode(LED_PIN, OUTPUT);
  led(false);
  pinMode(BTN_PIN, INPUT_PULLUP);

  Serial.begin(115200);
  delay(200);
  loadCfg();
  Serial.printf("\nAromaDiffuser  proto=%s\n", useOsc ? "OSC" : "sACN");

  configure(digitalRead(BTN_PIN) == LOW);   // BOOT held = open config portal
  Serial.printf("WiFi up: %s\n", WiFi.localIP().toString().c_str());

  if (useOsc) {
    udp.begin(oscPort);
    Serial.printf("OSC: listening %s on UDP %u\n", oscAddr.c_str(), oscPort);
  } else {
    sacnBegin(universe);
    Serial.printf("sACN: universe=%u channel=%u threshold=%u\n", universe, channel, threshold);
    lastPacket = millis();
  }

  startWeb();
}

void loop() {
  if (rebootAt && millis() >= rebootAt) ESP.restart();   // deferred restart after /save

  if (WiFi.status() != WL_CONNECTED) {        // lost network = lost control = scent OFF
    setPump(false);
    led((millis() / 150) & 1);
    return;
  }

  if (millis() < puffUntil) {                 // web "Test" button overrides the protocol
    setPump(true);
    led(true);
    return;
  }

  if (useOsc) {
    pollOsc();                                // events hold last state (no stream timeout)
  } else {
    pollSacn();                               // updates lastPacket + pump on each frame
    if (millis() - lastPacket > FAILSAFE_MS) setPump(false);   // stream stopped -> scent off
  }

  if (pumpOn && maxOn && millis() - pumpSince >= (uint32_t)maxOn * 1000) {
    Serial.println("[pump] max-on watchdog");
    setPump(false);                           // stuck-on safety (both protocols)
  }

  led(pumpOn);
}

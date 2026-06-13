/*
 * ================================================
 * ESP32 DROWSINESS ALERT SYSTEM - PlatformIO
 * ================================================
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

// ==========================================
// KONFIGURASI WIFI - GANTI INI!
// ==========================================
const char* ssid = "Xiaomi 14T";         // ⬅️ GANTI!
const char* password = "Chandradra21"; // ⬅️ GANTI!

// Hostname untuk mDNS
const char* hostname = "drowsiness";

// ==========================================
// KONFIGURASI PIN
// ==========================================
const int BUZZER_PIN = 25;
const int LED_STATUS = 2;
const int LED_WARNING = 26;

// ==========================================
// VARIABEL GLOBAL
// ==========================================
WebServer server(80);
unsigned long lastAlarmTime = 0;
const unsigned long ALARM_COOLDOWN = 2000;
int alarmCount = 0;
String lastAlertType = "";
String deviceIP = "";

// ==========================================
// FUNGSI BUZZER
// ==========================================

void playAlarmPattern(String alertType) {
  if (alertType == "eyes") {
    for (int i = 0; i < 3; i++) {
      tone(BUZZER_PIN, 2500, 500);
      delay(600);
      tone(BUZZER_PIN, 2000, 200);
      delay(300);
    }
  } else if (alertType == "yawn") {
    for (int i = 0; i < 5; i++) {
      tone(BUZZER_PIN, 2000, 300);
      delay(400);
    }
  } else {
    tone(BUZZER_PIN, 2500, 1000);
    delay(1000);
  }
  noTone(BUZZER_PIN);
}

void shortBeep() {
  tone(BUZZER_PIN, 2000, 100);
  delay(150);
  noTone(BUZZER_PIN);
}

void successBeep() {
  tone(BUZZER_PIN, 2000, 200);
  delay(250);
  tone(BUZZER_PIN, 2500, 200);
  delay(250);
  noTone(BUZZER_PIN);
}

void errorBeep() {
  for(int i=0; i<3; i++) {
    tone(BUZZER_PIN, 1000, 200);
    delay(300);
  }
  noTone(BUZZER_PIN);
}

// ==========================================
// HTTP HANDLERS
// ==========================================

void handleAlarm() {
  unsigned long currentTime = millis();
  
  if (currentTime - lastAlarmTime < ALARM_COOLDOWN) {
    server.send(200, "text/plain", "OK - Cooldown active");
    return;
  }
  
  String alertType = "default";
  if (server.hasArg("type")) {
    alertType = server.arg("type");
  }
  
  lastAlertType = alertType;
  lastAlarmTime = currentTime;
  alarmCount++;
  
  digitalWrite(LED_WARNING, HIGH);
  
  Serial.println("⚠️ ALARM TRIGGERED!");
  Serial.println("Type: " + alertType);
  Serial.println("Time: " + String(millis()/1000) + "s");
  Serial.println("Count: " + String(alarmCount));
  Serial.println("---");
  
  playAlarmPattern(alertType);
  
  digitalWrite(LED_WARNING, LOW);
  
  String response = "{\"status\":\"success\",\"type\":\"" + alertType + "\",\"count\":" + String(alarmCount) + "}";
  server.send(200, "application/json", response);
}

void handleTest() {
  Serial.println("🔔 Testing buzzer...");
  
  digitalWrite(LED_WARNING, HIGH);
  tone(BUZZER_PIN, 2500, 500);
  delay(600);
  noTone(BUZZER_PIN);
  digitalWrite(LED_WARNING, LOW);
  
  server.send(200, "text/plain", "Buzzer test complete!");
}

void handleStatus() {
  String html = "<!DOCTYPE html><html><head>";
  html += "<meta charset='UTF-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<title>ESP32 Drowsiness Alert</title>";
  html += "<style>";
  html += "body{font-family:Arial;margin:0;padding:20px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh}";
  html += ".container{max-width:600px;margin:0 auto;background:white;padding:30px;border-radius:15px;box-shadow:0 10px 40px rgba(0,0,0,0.3)}";
  html += "h1{color:#667eea;margin:0 0 20px 0;font-size:28px;border-bottom:3px solid #667eea;padding-bottom:15px}";
  html += ".card{margin:20px 0;padding:20px;background:#f8f9fa;border-radius:10px;border-left:4px solid #667eea}";
  html += ".label{font-weight:bold;color:#555;margin:8px 0}";
  html += ".value{color:#667eea;font-size:18px;font-weight:bold}";
  html += ".status-ok{color:#28a745;font-weight:bold;font-size:20px}";
  html += ".button{display:inline-block;margin:10px 5px;padding:12px 24px;background:#667eea;color:white;text-decoration:none;border-radius:8px;border:none;cursor:pointer;font-size:16px;transition:all 0.3s}";
  html += ".button:hover{background:#5568d3;transform:translateY(-2px);box-shadow:0 5px 15px rgba(102,126,234,0.4)}";
  html += ".alert{background:#fff3cd;border-left:4px solid #ffc107;padding:15px;margin:20px 0;border-radius:8px}";
  html += ".ip-display{background:#667eea;color:white;padding:15px;border-radius:8px;text-align:center;font-size:20px;font-weight:bold;margin:20px 0}";
  html += "</style></head><body>";
  
  html += "<div class='container'>";
  html += "<h1>🚨 ESP32 Drowsiness Alert</h1>";
  
  html += "<div class='ip-display'>";
  html += "📍 IP: " + deviceIP;
  html += "</div>";
  
  html += "<div class='card'>";
  html += "<div class='label'>Status: <span class='status-ok'>✅ ONLINE</span></div>";
  html += "<div class='label'>Hostname: <span class='value'>http://" + String(hostname) + ".local</span></div>";
  html += "<div class='label'>Alarms: <span class='value'>" + String(alarmCount) + "</span></div>";
  html += "<div class='label'>Last Alert: <span class='value'>" + (lastAlertType == "" ? "None" : lastAlertType) + "</span></div>";
  html += "<div class='label'>Uptime: <span class='value'>" + String(millis()/1000) + "s</span></div>";
  html += "<div class='label'>Free Heap: <span class='value'>" + String(ESP.getFreeHeap()) + " bytes</span></div>";
  html += "</div>";
  
  html += "<div style='text-align:center'>";
  html += "<button class='button' onclick='testBuzzer()'>🔔 Test</button>";
  html += "<button class='button' onclick='location.reload()'>🔄 Refresh</button>";
  html += "</div>";
  
  html += "<div class='alert'>";
  html += "<strong>⚙️ Python Config:</strong><br><br>";
  html += "<code>ESP32_IP = \"" + deviceIP + "\"</code>";
  html += "</div>";
  
  html += "</div>";
  
  html += "<script>";
  html += "function testBuzzer(){fetch('/test').then(r=>r.text()).then(d=>alert(d))}";
  html += "</script>";
  
  html += "</body></html>";
  
  server.send(200, "text/html", html);
}

void handleRoot() {
  handleStatus();
}

void handleNotFound() {
  server.send(404, "text/plain", "404: Not Found");
}

// ==========================================
// DISPLAY INFO
// ==========================================

void displayIPInfo() {
  Serial.println("\n");
  Serial.println("╔════════════════════════════════════════════════╗");
  Serial.println("║          SISTEM SIAP DIGUNAKAN! ✅            ║");
  Serial.println("╚════════════════════════════════════════════════╝");
  Serial.println();
  Serial.println("📍 IP Address ESP32:");
  Serial.println("   ┌─────────────────────────────────────┐");
  Serial.println("   │  " + deviceIP + "                 │");
  Serial.println("   └─────────────────────────────────────┘");
  Serial.println();
  Serial.println("🌐 Akses Web Interface:");
  Serial.println("   http://" + deviceIP);
  Serial.println("   http://" + String(hostname) + ".local");
  Serial.println();
  Serial.println("⚙️  Konfigurasi Python:");
  Serial.println("   ESP32_IP = \"" + deviceIP + "\"");
  Serial.println();
  Serial.println("════════════════════════════════════════════════");
  Serial.println();
}

// ==========================================
// SETUP
// ==========================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n\n");
  Serial.println("╔════════════════════════════════════════════════╗");
  Serial.println("║   ESP32 DROWSINESS ALERT - PlatformIO v2.0   ║");
  Serial.println("╚════════════════════════════════════════════════╝");
  Serial.println();
  
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_STATUS, OUTPUT);
  pinMode(LED_WARNING, OUTPUT);
  
  digitalWrite(LED_STATUS, LOW);
  digitalWrite(LED_WARNING, LOW);
  
  shortBeep();
  
  Serial.println("📡 Connecting to WiFi...");
  Serial.println("   SSID: " + String(ssid));
  Serial.print("   ");
  
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(hostname);
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print("▓");
    digitalWrite(LED_STATUS, !digitalRead(LED_STATUS));
    attempts++;
  }
  Serial.println();
  
  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_STATUS, HIGH);
    deviceIP = WiFi.localIP().toString();
    
    Serial.println("\n✅ WiFi Connected!");
    
    if (MDNS.begin(hostname)) {
      Serial.println("✅ mDNS Started!");
      MDNS.addService("http", "tcp", 80);
    }
    
    successBeep();
    
  } else {
    Serial.println("\n❌ WiFi Connection FAILED!");
    errorBeep();
    return;
  }
  
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/alarm", HTTP_POST, handleAlarm);
  server.on("/test", handleTest);
  server.onNotFound(handleNotFound);
  
  server.begin();
  
  displayIPInfo();
  
  delay(500);
  shortBeep();
  delay(200);
  shortBeep();
}

// ==========================================
// LOOP
// ==========================================

void loop() {
  server.handleClient();
  // Note: ESP32 mDNS tidak perlu update() seperti ESP8266
  
  static unsigned long lastBlink = 0;
  if (millis() - lastBlink > 2000) {
    digitalWrite(LED_STATUS, !digitalRead(LED_STATUS));
    lastBlink = millis();
  }
  
  static unsigned long lastStatus = 0;
  if (millis() - lastStatus > 30000) {
    Serial.println("💚 OK - Uptime: " + String(millis()/1000) + "s - Alarms: " + String(alarmCount));
    lastStatus = millis();
  }
}
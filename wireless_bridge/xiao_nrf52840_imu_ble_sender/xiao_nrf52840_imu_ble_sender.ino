#include <LSM6DS3.h>
#include <Wire.h>
#include <bluefruit.h>

LSM6DS3 myIMU(I2C_MODE, 0x6A);

BLEService pillowService(0xAAAA);
BLECharacteristic stateChar(0xBBBB);

#define LEFT_RIGHT_THRESHOLD 0.60f
#define SNIFFING_X_LOW 0.53f
#define SNIFFING_X_HIGH 0.59f
#define SEND_INTERVAL_MS 300

static char lastState = '?';
static uint32_t notifyCount = 0;

static char classifyPosture(float aX, float aY) {
  if (aY >= LEFT_RIGHT_THRESHOLD) {
    return 'R';
  }
  if (aY <= -LEFT_RIGHT_THRESHOLD) {
    return 'L';
  }
  if (aX >= SNIFFING_X_LOW && aX <= SNIFFING_X_HIGH) {
    return 'S';
  }
  if (aX < SNIFFING_X_LOW) {
    return 'F';
  }
  return 'O';
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);

  if (myIMU.begin() != 0) {
    Serial.println("IMU init failed.");
    while (1) {
      delay(100);
    }
  }

  Bluefruit.begin();
  Bluefruit.setName("SmartPillow");
  Bluefruit.setTxPower(4);

  pillowService.begin();
  stateChar.setProperties(CHR_PROPS_READ | CHR_PROPS_NOTIFY);
  stateChar.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  stateChar.setFixedLen(1);
  stateChar.begin();
  stateChar.write8('N');

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(pillowService);
  Bluefruit.Advertising.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.start(0);

  Serial.println("SmartPillow IMU BLE sender started.");
  Serial.println("States: L=left, R=right, S=sniffing, F=front-low, O=angle-over.");
}

void loop() {
  float aX = myIMU.readFloatAccelX();
  float aY = myIMU.readFloatAccelY();
  char state = classifyPosture(aX, aY);

  digitalWrite(LED_BUILTIN, (state == 'L' || state == 'R' || state == 'S') ? LOW : HIGH);

  stateChar.write8(state);
  if (stateChar.notifyEnabled()) {
    stateChar.notify8(state);
    notifyCount++;
  }

  if (state != lastState) {
    Serial.print("state changed: ");
    Serial.print(lastState);
    Serial.print(" -> ");
    Serial.println(state);
    lastState = state;
  }

  Serial.print("aX=");
  Serial.print(aX, 3);
  Serial.print(" aY=");
  Serial.print(aY, 3);
  Serial.print(" state=");
  Serial.print(state);
  Serial.print(" notify=");
  Serial.println(notifyCount);

  delay(SEND_INTERVAL_MS);
}

#include <BLEDevice.h>
#include <BLEScan.h>

static BLEUUID serviceUUID((uint16_t)0xAAAA);
static BLEUUID charUUID((uint16_t)0xBBBB);

// XIAO ESP32-S3 exposes its hardware UART on the side header as D6/TX and D7/RX.
// Arduino pin constants D6/D7 map to GPIO43/GPIO44 on the Seeed XIAO ESP32-S3.
#ifndef D6
#define D6 43
#endif
#ifndef D7
#define D7 44
#endif

#define STM32_TX_PIN D6
#define STM32_RX_PIN D7
#define STM32_UART_BAUD 9600

static boolean doConnect = false;
static boolean connected = false;
static BLEAdvertisedDevice *myDevice = nullptr;
static BLERemoteCharacteristic *pRemoteCharacteristic = nullptr;

static uint32_t notifyCount = 0;
static uint32_t uartTxCount = 0;
static char lastState = '?';

static bool isValidState(char state) {
  return state == 'L' || state == 'R' || state == 'N' ||
         state == 'S' || state == 'F' || state == 'O';
}

static void notifyCallback(
  BLERemoteCharacteristic *pBLERemoteCharacteristic,
  uint8_t *pData,
  size_t length,
  bool isNotify) {

  if (length == 0) {
    return;
  }

  char rxData = (char)pData[0];
  notifyCount++;
  lastState = rxData;

  Serial.print("BRIDGE_NOTIFY state=");
  Serial.print(rxData);
  Serial.print(" notify=");
  Serial.print(notifyCount);

  if (isValidState(rxData)) {
    Serial1.write((uint8_t)rxData);
    uartTxCount++;
    Serial.print(" uart_tx=");
    Serial.println(uartTxCount);
  } else {
    Serial.println(" uart_tx=unchanged invalid=1");
  }
}

class MyClientCallback : public BLEClientCallbacks {
  void onConnect(BLEClient *pclient) {
    connected = true;
    Serial.println("BRIDGE_CONNECTED target=SmartPillow");
  }

  void onDisconnect(BLEClient *pclient) {
    connected = false;
    pRemoteCharacteristic = nullptr;
    Serial.println("BRIDGE_DISCONNECTED target=SmartPillow");
  }
};

bool connectToServer() {
  BLEClient *pClient = BLEDevice::createClient();
  pClient->setClientCallbacks(new MyClientCallback());

  if (!pClient->connect(myDevice)) {
    Serial.println("BLE connect failed.");
    return false;
  }

  BLERemoteService *pRemoteService = pClient->getService(serviceUUID);
  if (pRemoteService == nullptr) {
    Serial.println("Target service 0xAAAA not found.");
    pClient->disconnect();
    return false;
  }

  pRemoteCharacteristic = pRemoteService->getCharacteristic(charUUID);
  if (pRemoteCharacteristic == nullptr) {
    Serial.println("Target characteristic 0xBBBB not found.");
    pClient->disconnect();
    return false;
  }

  if (pRemoteCharacteristic->canNotify()) {
    pRemoteCharacteristic->registerForNotify(notifyCallback);
    Serial.println("Notify registered.");
  } else {
    Serial.println("Characteristic cannot notify.");
    pClient->disconnect();
    return false;
  }

  return true;
}

class MyAdvertisedDeviceCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) {
    if (advertisedDevice.getName() == "SmartPillow" ||
        advertisedDevice.isAdvertisingService(serviceUUID)) {
      BLEDevice::getScan()->stop();
      if (myDevice != nullptr) {
        delete myDevice;
      }
      myDevice = new BLEAdvertisedDevice(advertisedDevice);
      doConnect = true;
    Serial.println("BRIDGE_FOUND target=SmartPillow");
    }
  }
};

void setup() {
  Serial.begin(115200);
  delay(200);

  Serial1.begin(STM32_UART_BAUD, SERIAL_8N1, STM32_RX_PIN, STM32_TX_PIN);
  Serial.println("BRIDGE_BOOT board=XIAO_ESP32S3 mode=BLE_TO_STM32_UART");
  Serial.println("Wire: XIAO ESP32-S3 D6/TX(GPIO43) -> STM32 PA10/RX1, common GND required.");

  BLEDevice::init("");
#if defined(ESP_PWR_LVL_P9)
  BLEDevice::setPower(ESP_PWR_LVL_P9);
#endif

  BLEScan *pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
  pBLEScan->setInterval(1349);
  pBLEScan->setWindow(449);
  pBLEScan->setActiveScan(true);
  pBLEScan->start(5, false);
}

void loop() {
  if (doConnect) {
    if (connectToServer()) {
      Serial.println("BRIDGE_READY path=NRF_BLE_TO_STM32_UART");
    } else {
      Serial.println("BRIDGE_CONNECT_FAILED action=rescan");
    }
    doConnect = false;
  }

  if (!connected && !doConnect) {
    BLEDevice::getScan()->start(5, false);
  }

  static uint32_t lastPrint = 0;
  if (millis() - lastPrint > 2000) {
    lastPrint = millis();
    Serial.print("BRIDGE_STATUS connected=");
    Serial.print(connected ? "yes" : "no");
    Serial.print(" last=");
    Serial.print(lastState);
    Serial.print(" notify=");
    Serial.print(notifyCount);
    Serial.print(" uart_tx=");
    Serial.println(uartTxCount);
  }

  delay(100);
}

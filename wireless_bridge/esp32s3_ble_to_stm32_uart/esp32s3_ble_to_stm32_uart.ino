/*
  파일 설명:
    XIAO ESP32-S3가 XIAO nRF52840 "SmartPillow" BLE notify를 구독하고,
    수신한 자세 토큰을 STM32 USART1 RX(PA10)로 전달하는 무선 브리지입니다.

  전체 흐름:
    1. nRF52840이 BLE service 0xAAAA / characteristic 0xBBBB로 L/R/N/S/F/O 토큰을 notify합니다.
    2. ESP32-S3가 해당 BLE 장치를 scan/connect하고 notifyCallback에서 1바이트 토큰을 받습니다.
    3. 유효한 토큰만 Serial1 UART 9600 bps로 STM32 PA10/RX1에 씁니다.
    4. STM32는 main.c의 IMU bridge 로직에서 토큰을 자세 상태로 해석해 사이드 에어백을 제어합니다.

  배선:
    XIAO ESP32-S3 D6/TX(GPIO43) -> STM32 PA10/RX1
    XIAO ESP32-S3 GND -> STM32 GND
*/
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

// STM32 펌웨어가 현재 인식하는 자세 토큰만 UART로 통과시켜 잘못된 BLE payload를 차단합니다.
static bool isValidState(char state) {
  return state == 'L' || state == 'R' || state == 'N' ||
         state == 'S' || state == 'F' || state == 'O';
}

// nRF52840 characteristic notify가 들어올 때마다 호출되어 상태 토큰을 STM32 UART로 중계합니다.
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
  // BLE 연결이 성립되면 loop의 rescan을 멈추고 상태 로그를 남깁니다.
  void onConnect(BLEClient *pclient) {
    connected = true;
    Serial.println("BRIDGE_CONNECTED target=SmartPillow");
  }

  // BLE 연결이 끊기면 characteristic 포인터를 지워 다음 scan/connect가 새로 잡히게 합니다.
  void onDisconnect(BLEClient *pclient) {
    connected = false;
    pRemoteCharacteristic = nullptr;
    Serial.println("BRIDGE_DISCONNECTED target=SmartPillow");
  }
};

// 발견된 SmartPillow 장치에 연결하고, service/characteristic을 찾은 뒤 notify callback을 등록합니다.
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
  // scan 결과 중 이름이나 service UUID가 맞는 장치를 찾으면 scan을 멈추고 연결 예약 플래그를 세웁니다.
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

// USB 로그, STM32 UART, BLE scan 설정을 초기화합니다.
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

// 연결 예약 처리, 연결이 끊겼을 때 rescan, 2초 간격 상태 로그를 반복합니다.
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

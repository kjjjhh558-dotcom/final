/*
  파일 설명:
    BLE를 배제하고 XIAO ESP32-S3 -> STM32 USART1 배선만 검증하는 UART smoke test입니다.

  사용 시점:
    nRF52840 BLE 송신이나 ESP32 BLE 연결이 불확실할 때 먼저 이 스케치를 올려
    STM32 PA10/RX1이 L/R/N/S/F/O 토큰을 받는지 확인합니다.

  배선:
    XIAO ESP32-S3 D6/TX(GPIO43) -> STM32 PA10/RX1
    XIAO ESP32-S3 GND -> STM32 GND
*/

#ifndef D6
#define D6 43
#endif
#ifndef D7
#define D7 44
#endif

#define STM32_TX_PIN D6
#define STM32_RX_PIN D7
#define STM32_UART_BAUD 9600

static const char states[] = {'L', 'R', 'N', 'S', 'F', 'O'};
static uint32_t txCount = 0;

// USB Serial 로그와 STM32로 나가는 Serial1 UART 9600 bps를 시작합니다.
void setup() {
  Serial.begin(115200);
  delay(300);

  Serial1.begin(STM32_UART_BAUD, SERIAL_8N1, STM32_RX_PIN, STM32_TX_PIN);
  Serial.println("XIAO ESP32-S3 UART-only STM32 test started.");
  Serial.println("Wire: XIAO D6/TX(GPIO43) -> STM32 PA10/RX1, XIAO GND -> STM32 GND.");
}

// 테스트 토큰을 0.5초마다 하나씩 순환 전송해 STM32 IMU bridge 카운터 증가를 확인합니다.
void loop() {
  char state = states[txCount % (sizeof(states) / sizeof(states[0]))];
  Serial1.write((uint8_t)state);

  Serial.print("sent to STM32: ");
  Serial.print(state);
  Serial.print(" count=");
  Serial.println(txCount + 1);

  txCount++;
  delay(500);
}

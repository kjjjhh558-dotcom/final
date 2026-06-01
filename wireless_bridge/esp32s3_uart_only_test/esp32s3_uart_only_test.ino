// UART-only smoke test for XIAO ESP32-S3 -> STM32 USART1.
// Upload this first if BLE is uncertain. It sends L/R/N/S/F/O repeatedly.

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

void setup() {
  Serial.begin(115200);
  delay(300);

  Serial1.begin(STM32_UART_BAUD, SERIAL_8N1, STM32_RX_PIN, STM32_TX_PIN);
  Serial.println("XIAO ESP32-S3 UART-only STM32 test started.");
  Serial.println("Wire: XIAO D6/TX(GPIO43) -> STM32 PA10/RX1, XIAO GND -> STM32 GND.");
}

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

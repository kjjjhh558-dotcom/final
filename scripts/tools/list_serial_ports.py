"""현재 PC에서 보이는 COM 포트와 설명을 출력합니다.

STM32, ESP32-S3, XIAO nRF52840 보드가 어느 포트로 잡혔는지 확인한 뒤 다른 도구 스크립트의 port 인자로 넣습니다."""

# 파일 설명: 현재 PC에서 사용 가능한 COM 포트를 출력합니다.
import serial.tools.list_ports

ports = serial.tools.list_ports.comports()

for p in ports:
    print(p.device, p.description)
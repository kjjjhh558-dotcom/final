# 파일 설명: 현재 PC에서 사용 가능한 COM 포트를 출력합니다.
import serial.tools.list_ports

ports = serial.tools.list_ports.comports()

for p in ports:
    print(p.device, p.description)
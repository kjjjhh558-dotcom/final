# -*- coding: utf-8 -*-
# 파일 설명: STM32 USB CDC 오디오 패킷의 수신 상태와 ADC 범위를 빠르게 점검합니다.
#
# receive_audio_test.py
#
# 목적:
#   STM32F407 + MAX9814 펌웨어가 USB CDC로 보내는 binary 오디오 패킷이
#   정상적으로 PC에 도착하는지 빠르게 확인하는 "수신 테스트용" 프로그램입니다.
#
# 실행하면 일어나는 일:
#   1. 지정한 COM 포트를 엽니다.
#   2. STM32가 보내는 패킷에서 MAGIC 값(0xAABBCCDD)을 찾아 동기화합니다.
#   3. 패킷 헤더(seq, samples)를 읽고 ADC payload를 uint16 배열로 복원합니다.
#   4. seq 번호가 건너뛰었는지 확인해서 패킷 손실을 감지합니다.
#   5. 약 20패킷마다 ADC min/max/mid, peak-to-peak, dropped count를 출력합니다.
#
# 활용 방법:
#   - 펌웨어의 ADC + DMA + TIM2 + USB CDC streaming이 살아 있는지 확인할 때 사용합니다.
#   - WAV 저장이나 라벨 생성은 하지 않습니다.
#   - 데이터셋 수집 전에 마이크 입력 레벨, DC offset, 패킷 손실 여부를 먼저 확인하는 용도입니다.
#
# 사용 방법:
#   1. 필요한 패키지 설치:
#        pip install pyserial numpy
#   2. STM32 보드 연결 후 장치 관리자에서 COM 포트 확인
#   3. 예시 실행:
#        python receive_audio_test.py COM5
#   4. 종료:
#        Ctrl + C
#
import sys
import struct
import time
import serial
import numpy as np

MAGIC = 0xAABBCCDD
HEADER_SIZE = 12
AUDIO_FORMAT_PCM16 = 1
BAUDRATE = 115200  # USB CDC에서는 큰 의미 없음


# 함수 설명: 파일, 시리얼, 모델, 설정 등 외부 입력을 읽어 메모리에 올립니다.
def read_exact(ser, n):
    data = bytearray()
    while len(data) < n:
        chunk = ser.read(n - len(data))
        if not chunk:
            continue
        data.extend(chunk)
    return bytes(data)


# 함수 설명: 입력 스트림이나 목록에서 필요한 위치와 대상을 찾아 동기화합니다.
def find_magic(ser):
    buf = bytearray()

    while True:
        b = ser.read(1)
        if not b:
            continue

        buf += b

        if len(buf) > 4:
            buf = buf[-4:]

        if len(buf) == 4:
            value = struct.unpack("<I", buf)[0]
            if value == MAGIC:
                return


# 함수 설명: 스크립트 진입점으로 인자를 읽고 전체 실행 흐름을 호출합니다.
def main():
    if len(sys.argv) < 2:
        print("사용법: python receive_audio_test.py COM포트")
        print("예시: python receive_audio_test.py COM5")
        return

    port = sys.argv[1]
    sample_format_arg = "auto"
    if len(sys.argv) >= 4 and sys.argv[2] == "--sample-format":
        sample_format_arg = sys.argv[3]
    elif len(sys.argv) >= 3 and sys.argv[2].startswith("--sample-format="):
        sample_format_arg = sys.argv[2].split("=", 1)[1]

    if sample_format_arg not in ("auto", "adc_u16", "pcm16"):
        print("--sample-format must be auto, adc_u16, or pcm16")
        return

    print(f"Opening {port}...")
    ser = serial.Serial(port, BAUDRATE, timeout=1)
    time.sleep(2)

    ser.reset_input_buffer()

    print("Waiting for STM32 audio packets...")

    expected_seq = None
    packet_count = 0
    dropped_count = 0
    start_time = time.time()

    try:
        while True:
            find_magic(ser)

            rest_header = read_exact(ser, HEADER_SIZE - 4)
            seq, samples, reserved = struct.unpack("<IHH", rest_header)

            payload_size = samples * 2
            payload = read_exact(ser, payload_size)

            adc = np.frombuffer(payload, dtype="<u2")

            if len(adc) != samples:
                print("payload size mismatch")
                continue

            if expected_seq is not None and seq != expected_seq:
                gap = seq - expected_seq
                if gap < 0:
                    gap = 0
                dropped_count += gap
                print(f"[WARN] seq jump: expected={expected_seq}, got={seq}")

            expected_seq = seq + 1
            packet_count += 1

            if packet_count % 20 == 0:
                elapsed = time.time() - start_time
                if sample_format_arg == "pcm16" or (sample_format_arg == "auto" and reserved == AUDIO_FORMAT_PCM16):
                    values = adc.view("<i2")
                    format_text = "pcm16"
                else:
                    values = adc
                    format_text = "adc_u16"

                sample_min = int(values.min())
                sample_max = int(values.max())
                sample_mid = int(values[len(values) // 2])
                p2p = sample_max - sample_min

                print(
                    f"packets={packet_count}, "
                    f"seq={seq}, "
                    f"samples={samples}, "
                    f"format={format_text}, "
                    f"reserved={reserved}, "
                    f"mid={sample_mid}, "
                    f"min={sample_min}, "
                    f"max={sample_max}, "
                    f"p2p={p2p}, "
                    f"dropped={dropped_count}, "
                    f"elapsed={elapsed:.1f}s"
                )

    except KeyboardInterrupt:
        print("\nStopped.")
        print(f"total packets: {packet_count}")
        print(f"dropped packets: {dropped_count}")

    finally:
        ser.close()


if __name__ == "__main__":
    main()

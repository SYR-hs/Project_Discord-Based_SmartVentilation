# main_bot.py
import discord                                # 디스코드 봇 기능을 사용하기 위한 메인 라이브러리
from discord.ext import commands, tasks       # 명령어 처리(@bot.command)와 백그라운드 반복 작업(@tasks.loop)을 위한 모듈
import requests                               # 기상청 API 서버와 HTTP 통신(GET/POST)을 하기 위한 라이브러리
from datetime import time, datetime, timedelta# 현재 시각 확인 및 시간차(3시간 전) 계산을 위한 모듈
import zoneinfo                               # 서버의 물리적 위치와 상관없이 시간대를 한국(KST)으로 고정하기 위한 모듈
from gpiozero import Buzzer, DigitalInputDevice # 라즈베리파이의 GPIO 핀(부저, 가스센서)을 제어하기 위한 하드웨어 라이브러리

# ==========================================
# 1. 환경 설정 및 API 인증키 (상수 정의)
# ==========================================
DISCORD_BOT_TOKEN = " " # 디스코드 봇 고유 토큰 (봇 로그인용, 개인정보라 빈칸 상태)
DISCORD_WEBHOOK_URL = " " # 정기 보고서를 특정 채널에 쏘기 위한 웹훅 주소 (개인정보라 빈칸 상태)
WEATHER_API_KEY = " " # 기상청 API 허브 데이터 접근 권한 키 (개인정보라 빈칸 상태)

# ==========================================
# 2. 기상청 외부 미세먼지(PM10) 데이터 수집 엔진
# ==========================================
def get_weather_realtime(stn="119"):          # stn="119"는 현재 위치(수원/오산 권역)의 기상청 지점 번호 (기본값)
    url = " " # PM10(미세먼지) 전용 기상청 API 엔드포인트 (개인정보라 빈칸 상태)
    
    KST = zoneinfo.ZoneInfo("Asia/Seoul")     # 한국 표준시 객체 생성
    now = datetime.now(KST)                   # 현재 KST 시각을 가져옴
    
    # 기상청 장비 점검이나 통신 지연에 대비해, 현재부터 3시간 전까지의 넉넉한 데이터를 한 번에 요청 (데이터 유실 방지)
    tm1 = (now - timedelta(hours=3)).strftime("%Y%m%d%H%M") # 검색 시작 시각 (3시간 전)
    tm2 = now.strftime("%Y%m%d%H%M")                        # 검색 종료 시각 (현재)
    
    params = {                                # API 서버에 보낼 요청 파라미터 딕셔너리 구성
        "authKey": WEATHER_API_KEY,           
        "stn": stn,
        "tm1": tm1,
        "tm2": tm2
    }
    
    try:
        response = requests.get(url, params=params, timeout=10) # API 서버에 GET 요청 발송 (10초 응답 대기 제한)
        if response.status_code == 200:                         # HTTP 상태 코드가 200(정상)일 경우
            text_data = response.text                           # 응답 데이터를 텍스트로 저장
            if "ERROR" in text_data or "AUTH" in text_data:     # 텍스트 내에 인증/권한 에러 문구가 있는지 1차 검열
                return {"success": False, "error": f"API 에러: {text_data.strip()}"}
            
            lines = text_data.strip().split('\n')               # 텍스트 데이터를 줄바꿈(\n) 기준으로 쪼개어 리스트로 변환
            
            # 최신 데이터를 찾기 위해 데이터의 맨 아래(가장 최근 시간)부터 위로 거꾸로 읽어 올라감
            for line in reversed(lines):
                line = line.strip()                             # 양옆 공백 제거
                if not line or line.startswith("#"):            # 빈 줄이거나 주석(#) 기호로 시작하는 헤더 라인은 무시
                    continue
                
                cols = line.split()                             # 정상적인 데이터 줄을 공백 기준으로 쪼개어 컬럼 분리
                if len(cols) >= 3:                              # 최소 3개 이상의 데이터(시간, 지점, 수치)가 있는지 확인
                    tm_str = cols[0]                            # 첫 번째 컬럼: 관측 시각 (예: 202606182100)
                    pm10_raw = cols[2]                          # 세 번째 컬럼: PM10 원시 데이터 (예: '14,000000,,=')
                    
                    # 🛠️ 데이터 정제(Cleansing): 기호(',', '=')를 제거하여 순수 숫자만 추출
                    clean_pm10 = pm10_raw.split(',')[0].replace('=', '').strip()
                    
                    try:
                        pm10_val = float(clean_pm10)            # 정제된 문자를 실수형(float) 연산 가능 숫자로 변환
                    except ValueError:
                        continue                                # 문자가 섞여 변환에 실패하면 다음(과거) 데이터로 넘어감
                    
                    if pm10_val < 0:                            # 수치가 음수(-99 등)이면 기상청 장비 점검 결측치이므로 건너뜀
                        continue 
                        
                    # 시각 데이터를 사람이 읽기 편한 'YYYY-MM-DD HH:MM' 포맷으로 예쁘게 변환
                    formatted_time = f"{tm_str[:4]}-{tm_str[4:6]}-{tm_str[6:8]} {tm_str[8:10]}:{tm_str[10:12]}"
                    
                    # 가장 먼저 찾은 '정상적인 최신 데이터'를 반환하고 즉시 함수 종료
                    return {"success": True, "pm10": pm10_val, "time": formatted_time}
                    
            # 3시간 치를 다 뒤졌는데도 정상 데이터가 없으면 에러 반환
            return {"success": False, "error": "최근 3시간 내 관측 데이터 없음"}
        else:
            return {"success": False, "error": f"HTTP Error: {response.status_code}"} # 404, 500 등 웹 서버 에러 처리
    except Exception as e:
        return {"success": False, "error": str(e)}              # 인터넷 끊김 등 파이썬 자체 예외 발생 시 처리

# ==========================================
# 3. 디스코드 봇 객체 및 하드웨어 핀 셋업
# ==========================================
intents = discord.Intents.default()           # 디스코드 기본 권한 객체 생성
intents.message_content = True                # 사용자가 입력한 메시지(명령어)의 내용을 봇이 읽을 수 있도록 허용
bot = commands.Bot(command_prefix='!', intents=intents) # 접두사 '!'에 반응하는 봇 객체 생성

bz = Buzzer(18)                               # BCM 18번 핀에 연결된 능동 피에조 부저 객체 생성
gas = DigitalInputDevice(17)                  # BCM 17번 핀에 연결된 MQ-2 가스 센서 (디지털 입력) 객체 생성
KST = zoneinfo.ZoneInfo("Asia/Seoul")         # 스케줄러 기준 시간대를 KST로 설정

# 🧠 실시간 감시 도배 방지용 글로벌 상태 변수
REALTIME_CHANNEL = None                       # 알림을 쏠 타겟 디스코드 채널 객체를 저장할 변수
LAST_GAS_STATE = 1                            # 센서의 직전 상태값 저장 (1: 정상, 0: 가스 검출). 초기값은 정상으로 세팅

# 30분 단위 정기 보고서 발송을 위한 스케줄 시간표(00분, 30분) 리스트 자동 생성
scheduled_times = []
for hour in range(24):
    scheduled_times.append(time(hour=hour, minute=0, tzinfo=KST))
    scheduled_times.append(time(hour=hour, minute=30, tzinfo=KST))

@bot.event
async def on_ready():                         # 봇이 디스코드 서버에 성공적으로 로그인했을 때 1회 실행되는 이벤트
    print(f"Logged in as {bot.user.name}")    # 터미널에 봇 이름 출력 (로그인 성공 확인용)
    print("통합 스마트 환경 알리미 시스템 가동 시작!")
    if not auto_ventilation_check.is_running(): # 정기 보고서 루프가 안 돌고 있으면 시작시킴
        auto_ventilation_check.start()

# ==========================================
# 4. 이벤트 기반 실시간 모니터링 엔진 (도배 방지 적용)
# ==========================================
@bot.command(name="실시간시작")
async def start_realtime(ctx):                # 사용자가 '!실시간시작'을 입력했을 때 실행
    global REALTIME_CHANNEL
    REALTIME_CHANNEL = ctx.channel            # 명령어를 입력한 현재 채팅방을 알림 수신 채널로 지정
    
    if realtime_gas_monitor.is_running():     # 이미 백그라운드 감시가 돌고 있다면 중복 실행 방지
        await ctx.send("이미 실시간 감시 모드가 가동 중입니다. 🕵️‍♂️")
    else:
        realtime_gas_monitor.start()          # 실시간 감시 루프 시작
        await ctx.send("🟢 **[실시간 감시 모드 ON]**\n지금부터 2초 간격으로 가스 누출을 감시하며, 위험 감지 시 즉각 알림을 보냅니다.")

@bot.command(name="실시간중지")
async def stop_realtime(ctx):                 # 사용자가 '!실시간중지'를 입력했을 때 실행
    if realtime_gas_monitor.is_running():
        realtime_gas_monitor.cancel()         # 백그라운드 실시간 감시 루프 강제 종료
        await ctx.send("🔴 **[실시간 감시 모드 OFF]**\n실시간 백그라운드 감시를 종료합니다. (`!실내상태` 수동 확인은 계속 가능합니다)")
    else:
        await ctx.send("실시간 감시 모드가 이미 꺼져 있습니다.")

@tasks.loop(seconds=2.0)                      # 2초마다 무한 반복되는 백그라운드 감시 루틴
async def realtime_gas_monitor():
    global LAST_GAS_STATE                     # 이전 상태값을 수정하기 위해 전역 변수 선언
    
    if REALTIME_CHANNEL is None:              # 알림을 보낼 채널이 없으면 루프 실행 안 함
        return
        
    current_gas_state = gas.value             # 가스 센서의 현재 디지털 값을 읽어옴 (1=정상, 0=위험)
    
    # 💥 이벤트 1: 방금 전까지 정상(1)이었는데, 지금 막 가스(0)가 감지된 찰나의 순간
    if current_gas_state == 0 and LAST_GAS_STATE == 1:
        bz.on()                               # 하드웨어 즉각 반응: 부저 사이렌 울림
        
        # 외부 대기 상태를 API로 즉시 조회하여 자연환기 가능 여부 판단
        res = get_weather_realtime(stn="119")
        outside_pm10 = res["pm10"] if res["success"] else 35.0 # API 실패 시 가상의 보통 수치(35)로 대체
        
        embed = discord.Embed(title="🚨 [긴급: 실내 유해 가스 감지됨!]", color=16711680) # 빨간색 임베드 뼈대 생성
        
        if outside_pm10 > 80:                 # 미세먼지가 나쁠 때 (환기 불가)
            embed.description = (
                f"**즉각적인 조치가 필요합니다!**\n"
                f"현재 외부 미세먼지 수치가 나쁨({outside_pm10} ㎍/㎥)이므로 창문을 열지 마세요.\n"
                f"👉 **내부 공기청정기 / 주방 배출 후드를 최대 강풍으로 가동하세요!**"
            )
        else:                                 # 미세먼지가 양호할 때 (환기 가능)
            embed.description = (
                f"**즉각적인 조치가 필요합니다!**\n"
                f"현재 외부 미세먼지 수치가 양호({outside_pm10} ㎍/㎥)합니다.\n"
                f"👉 **즉시 창문을 열어 자연 환기를 실시하세요!**"
            )
        await REALTIME_CHANNEL.send(embed=embed) # 완성된 경고 메시지를 지정된 채널로 발송
        
    # 🍃 이벤트 2: 가스가 차있는 상태(0)였는데, 방금 막 공기가 깨끗해진(1) 찰나의 순간
    elif current_gas_state == 1 and LAST_GAS_STATE == 0:
        bz.off()                              # 상황 종료: 부저 끄기
        embed = discord.Embed(
            title="✅ [실내 환경 회복 알림]", 
            description="가스/연기가 모두 흩어져 실내 공기가 다시 쾌적한 상태로 돌아왔습니다. 부저를 종료합니다.", 
            color=3066993                       # 초록색
        )
        await REALTIME_CHANNEL.send(embed=embed) # 안심 알림 1회 발송
        
    # 루프의 마지막: '현재 상태'를 '과거 상태' 변수에 덮어씌워 다음 2초 뒤 루프 때 비교군으로 사용
    LAST_GAS_STATE = current_gas_state

# ==========================================
# 5. 수동 제어 명령어 및 30분 정기 보고서 루프
# ==========================================
@bot.command(name="실내상태")                 
async def measure_indoor(ctx):                # 사용자가 수동으로 현재 상태를 요구할 때 실행 (!실내상태)
    await ctx.send("🔍 센서 데이터를 분석하여 최적의 환기 솔루션을 계산 중입니다...")
    is_gas_detected = (gas.value == 0)        # 물리 센서의 현재 핀 상태 평가
    res = get_weather_realtime(stn="119")     # 기상청 데이터 호출
    outside_pm10 = res["pm10"] if res["success"] else 35.0

    if is_gas_detected:                       # 실내 가스가 감지되었을 경우 (환기 필요)
        bz.on()
        indoor_status = "⚠️ 위험 (가스 감지)"
        ventilation_needed = "⭕ 필요"
        if outside_pm10 > 80:                 # 미세먼지도 나쁠 경우 (최악의 상황)
            outdoor_status = f"🚨 나쁨 ({outside_pm10} ㎍/㎥)"
            final_decision = "❌ **창문 개방 금지**\n👉 공기청정기/후드를 가동하세요!"
            embed_color = 16711680
        else:                                 # 미세먼지가 양호할 경우
            outdoor_status = f"✅ 양호 ({outside_pm10} ㎍/㎥)"
            final_decision = "🟢 **자연 환기 권장**\n👉 즉시 창문을 열어 환기하세요!"
            embed_color = 16753920
    else:                                     # 실내 가스가 없고 쾌적한 경우
        bz.off()
        indoor_status = "✅ 쾌적"
        ventilation_needed = "❌ 불필요"
        outdoor_status = f"{outside_pm10} ㎍/㎥"
        final_decision = "🔵 **현재 상태 유지**\n👉 실내 공기가 깨끗합니다."
        embed_color = 3066993

    # 판단된 결과들을 디스코드 UI(Embed)의 Field 표 형태로 깔끔하게 조립
    embed = discord.Embed(title="📊 [스마트 환경 판단 결과]", color=embed_color)
    embed.add_field(name="🏠 실내 상태", value=indoor_status, inline=True)
    embed.add_field(name="💨 환기 필요", value=ventilation_needed, inline=True)
    embed.add_field(name="😷 외부 미세먼지", value=outdoor_status, inline=False)
    embed.add_field(name="💡 최종 지침", value=final_decision, inline=False)
    await ctx.send(embed=embed)               # 조립된 표 메시지 전송

@bot.command(name="대기상태")
async def check_weather(ctx):                 # 센서 개입 없이 외부 미세먼지만 단독 조회할 때 사용 (!대기상태)
    await ctx.send("🔍 현재 기상청 실시간 미세먼지 데이터를 조회 중입니다...")
    res = get_weather_realtime(stn="119")
    if res["success"]:
        await ctx.send(f"=== 📌 실외 미세먼지(PM10): {res['pm10']} ㎍/㎥ (기준 시각: {res['time']}) ===")
    else:
        await ctx.send(f"❌ [API 연동 실패]\n`{res['error']}`")

@tasks.loop(time=scheduled_times)             # 매시 정각(00분)과 30분마다 트리거되는 정기 보고 루프
async def auto_ventilation_check():
    await bot.wait_until_ready()              # 봇이 완전히 로그인될 때까지 대기
    res = get_weather_realtime(stn="119")
    outside_pm10 = res["pm10"] if res["success"] else 35.0
    is_gas_detected = (gas.value == 0)

    # 보고서 뼈대 생성
    embed_data = {"title": "🔄 [30분 정기 실내 환경 보고서]", "color": 65280}

    # 현재 실내외 데이터를 조합하여 보고 내용 채우기
    if is_gas_detected:
        bz.on()
        if outside_pm10 > 80:  
            embed_data["title"] = "⚠️ [실내 환기 보류 알림]"
            embed_data["description"] = f"🚨 **실내 가스 감지 (환기 필요 O)**\n외부 미세먼지 나쁨({outside_pm10} ㎍/㎥). 창문 닫고 공기청정기 가동!"
            embed_data["color"] = 16711680
        else:
            embed_data["title"] = "🚨 [실내 자연 환기 적극 권장]"
            embed_data["description"] = f"🚨 **실내 가스 감지 (환기 필요 O)**\n외부 미세먼지 양호({outside_pm10} ㎍/㎥). 즉시 창문을 여세요!"
            embed_data["color"] = 16753920
    else:
        bz.off()
        embed_data["description"] = f"✅ **실내 쾌적 (환기 필요 X)**\n외부 미세먼지: {outside_pm10} ㎍/㎥."
        embed_data["color"] = 3066993

    # 봇의 채팅(ctx.send) 대신 Webhook을 사용하여 특정 채널에 메시지 강제 주입(POST)
    requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed_data]})

@bot.command(name="off")
async def shutdown_bot(ctx):                  # 라즈베리파이 터미널 조작 없이 디스코드에서 원격으로 봇을 끌 때 사용 (!off)
    await ctx.send("🔌 봇 프로세스를 완전히 종료하고 오프라인 상태로 전환합니다.")
    bz.off()                                  # 봇이 꺼지기 전 부저가 계속 우는 것을 방지
    await bot.close()                         # 디스코드 클라이언트 연결 안전 종료

bot.run(DISCORD_BOT_TOKEN)                    # 봇 실행 (스크립트의 가장 마지막에서 실행을 블로킹하며 대기)

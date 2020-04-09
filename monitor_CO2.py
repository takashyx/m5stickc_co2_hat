import wifiCfg
from m5stack import *
import machine
import gc
import utime
import uos
import _thread
import math
import time


# 変数宣言
Disp_mode = 0     # グローバル
lcd_mute = False  # グローバル
data_mute = False  # グローバル
co2_interval = 5     # MH-19Bへco2測定値要求コマンドを送るサイクル（秒）
TIMEOUT = 30    # 何らかの事情でCO2更新が止まった時のタイムアウト（秒）のデフォルト値
CO2_RED = 1500  # co2濃度の赤色閾値（ppm）
CO2_YELLOW = 1000  # co2濃度の黄色閾値（ppm）
co2 = 0
preheat_count = 180  # センサー安定後数値が取れるようになるまでの時間


# @cinimlさんのファーム差分吸収ロジック
class AXPCompat(object):
    def __init__(self):
        if(hasattr(axp, 'setLDO2Vol')):
            self.setLDO2Vol = axp.setLDO2Vol
        else:
            self.setLDO2Vol = axp.setLDO2Volt


axp = AXPCompat()


# PWM用パルス関数
def pulse(l, t):
    for i in range(100):
        l.duty(int((math.sin(i / 50 * math.pi) * 50) + 50))
        time.sleep_ms(t)


# LED PWMスレッド関数
def led_controller():
    global CO2_RED
    global co2

    # setup LED PWM
    frequency = 5000
    g10 = machine.PWM(machine.Pin(10), frequency)
    for i in range(3):
        g10.duty(0)
        time.sleep_ms(100)
        g10.duty(100)
        time.sleep_ms(100)

    while True:
        if co2 >= CO2_RED and not lcd_mute:
            pulse(g10, 15)
        else:
            g10.duty(100)
            time.sleep_ms(200)


# 表示OFFボタン処理スレッド関数
def buttonA_wasPressed():
    global lcd_mute

    if lcd_mute:
        lcd_mute = False
    else:
        lcd_mute = True

    if lcd_mute:
        axp.setLDO2Vol(0)  # バックライト輝度調整（OFF）
    else:
        axp.setLDO2Vol(2.7)  # バックライト輝度調整（中くらい）


# 表示切替ボタン処理スレッド関数
def buttonB_wasPressed():
    global Disp_mode
    if Disp_mode == 1:
        Disp_mode = 0
    else:
        Disp_mode = 1
    draw_lcd()


def preheat_timer_count():
    global Disp_mode
    global preheat_count

    lcd.clear()
    while True:
        if preheat_count > 0:
            fc = lcd.YELLOW
            status = "Preheating... " + str(preheat_count)
            preheat_count = preheat_count - 1
        else:
            fc = lcd.WHITE
            status = "OK"

        if Disp_mode == 1:  # 表示回転処理
            lcd.rect(67, 0, 80, 160, lcd.BLACK, lcd.BLACK)
            lcd.line(66, 0, 66, 160, lcd.LIGHTGREY)
            lcd.font(lcd.FONT_DefaultSmall, rotate=90)
            lcd.print(status, 78, 40, fc)
        else:
            lcd.rect(0, 0, 13, 160, lcd.BLACK, lcd.BLACK)
            lcd.line(14, 0, 14, 160, lcd.LIGHTGREY)
            lcd.font(lcd.FONT_DefaultSmall, rotate=270)
            lcd.print(status, 2, 125, fc)
        utime.sleep(1)

# 表示モード切替時の枠描画処理関数


def draw_lcd():

    lcd.clear()
    draw_co2()


def draw_co2():
    global Disp_mode
    global lcd_mute
    global data_mute
    global CO2_RED
    global co2

    if data_mute or (co2 == 0):  # タイムアウトで表示ミュートされてるか、初期値のままならco2値非表示（黒文字化）
        fc = lcd.LIGHTGREY
    else:
        if co2 >= CO2_RED:  # CO2濃度閾値超え時は文字が赤くなる
            fc = lcd.RED
        elif co2 >= CO2_YELLOW:  # CO2濃度閾値超え時は文字が黄色くなる
            fc = lcd.YELLOW
        else:
            fc = lcd.WHITE

    if str(co2) == '0':
        co2_str = '---'
    else:
        co2_str = str(co2)

    if Disp_mode == 1:  # 表示回転処理
        lcd.rect(0, 0, 65, 160, lcd.BLACK, lcd.BLACK)
        lcd.font(lcd.FONT_DejaVu18, rotate=90)  # 単位(ppm)の表示
        lcd.print('ppm', 37, 105, fc)
        lcd.font(lcd.FONT_DejaVu24, rotate=90)  # co2値の表示

        lcd.print(co2_str, 40, 125 - (len(co2_str) * 24), fc)
    else:
        lcd.rect(15, 0, 80, 160, lcd.BLACK, lcd.BLACK)
        lcd.font(lcd.FONT_DejaVu18, rotate=270)  # 単位(ppm)の表示
        lcd.print('ppm', 43, 55, fc)
        lcd.font(lcd.FONT_DejaVu24, rotate=270)  # co2値の表示
        lcd.print(co2_str, 40, 35 + (len(co2_str) * 24), fc)


# MH-Z19Bデータのチェックサム確認関数
def checksum_chk(data):
    sum = 0
    for a in data[1:8]:
        sum = (sum + a) & 0xff
    c_sum = 0xff - sum + 1
    if c_sum == data[8]:
        return True
    else:
        print("c_sum un match!!")
        return False


# co2_set.txtの存在/中身チェック関数
def co2_set_filechk():
    global CO2_RED
    global TIMEOUT

    scanfile_flg = False
    for file_name in uos.listdir('/flash'):
        if file_name == 'co2_set.txt':
            scanfile_flg = True

    if scanfile_flg:
        print('>> found [co2_set.txt] !')
        with open('/flash/co2_set.txt', 'r') as f:
            for file_line in f:
                filetxt = file_line.strip().split(':')
                if filetxt[0] == 'CO2_RED':
                    if int(filetxt[1]) >= 1:
                        CO2_RED = int(filetxt[1])
                        print('- CO2_RED: ' + str(CO2_RED))
                elif filetxt[0] == 'TIMEOUT':
                    if int(filetxt[1]) >= 1:
                        TIMEOUT = int(filetxt[1])
                        print('- TIMEOUT: ' + str(TIMEOUT))

    else:
        print('>> no [co2_set.txt] !')
    return scanfile_flg


# メインプログラムはここから（この上はプログラム内関数）


# 画面初期化
axp.setLDO2Vol(2.7)  # バックライト輝度調整（中くらい）

# ユーザー設定ファイル読み込み
co2_set_filechk()

# RTC設定
utime.localtime(0)

# MH-19B UART設定
mhz19b = machine.UART(1, tx=0, rx=26)
mhz19b.init(9600, bits=8, parity=None, stop=1)
mhz19b.read()

# ボタン検出スレッド起動
btnA.wasPressed(buttonA_wasPressed)
btnB.wasPressed(buttonB_wasPressed)

# タイムカウンタ初期値設定
co2_tc = utime.time()

# LED表示スレッド起動
_thread.start_new_thread(led_controller, ())

# タイマー表示スレッド起動
_thread.start_new_thread(preheat_timer_count, ())

# メインルーチン
while True:
    if (utime.time() - co2_tc) >= co2_interval:  # co2要求コマンド送信
        mhz19b_data = bytearray(9)
        mhz19b.read()  # clear buffer
        mhz19b.write(b'\xff\x01\x86\x00\x00\x00\x00\x00\x79')   # co2測定値リクエスト
        utime.sleep(0.1)
        mhz19b.readinto(mhz19b_data, len(mhz19b_data))
        # co2測定値リクエストの応答
        if mhz19b_data[0] == 0xff and mhz19b_data[1] == 0x86 and checksum_chk(
                mhz19b_data):    # 応答かどうかの判定とチェックサムチェック
            co2_tc = utime.time()
            co2 = mhz19b_data[2] * 256 + mhz19b_data[3]
            data_mute = False
            draw_co2()
        utime.sleep(1)

    if (utime.time() - co2_tc) >= TIMEOUT:  # co2応答が一定時間無い場合はCO2値表示のみオフ
        data_mute = True
        draw_co2()

    utime.sleep(0.5)
    gc.collect()

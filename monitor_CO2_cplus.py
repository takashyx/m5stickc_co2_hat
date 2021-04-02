from m5stack import *
import machine
import gc
import utime
import uos
import _thread
import math


# 変数宣言
lcd_mute = False  # グローバル
data_mute = False  # グローバル
disp_mode = 0

co2_interval = 1     # MH-19B/Cへco2測定値要求コマンドを送るサイクル（秒）
TIMEOUT = 5    # 何らかの事情でCO2更新が止まった時のタイムアウト（秒）のデフォルト値
CO2_RED = 1500  # co2濃度の赤色閾値（ppm） LEDも点滅
CO2_YELLOW = 1000  # co2濃度の黄色閾値（ppm）
co2 = 0
co2_str = '---'
preheat_count = 60  # センサー安定後数値が取れるようになるまでの時間 MH-19B :180 MH-19C:60

preheat_status = ""
preheat_status_fc = lcd.BLACK

DARK_RED = 0x7F0000
DARK_YELLOW = 0x5F5F00
DARK_WHITE = 0x3F3F3F


# graph class ring buffer and draw
class GraphData:
    global CO2_RED
    global CO2_YELLOW

    def __init__(self, size):
        self.buffer = [0 for i in range(0, size)]
        self.start = 0
        self.end = 0
        self.size = size

    def __len__(self):
        return self.end - self.start

        self.size = size

    def add(self, val):
        self.buffer[self.end] = val
        self.end = (self.end + 1) % len(self.buffer)

    def get(self, index=None):
        if index is not None:
            return self.buffer[index]

        value = self.buffer[self.top]
        self.top = (self.top + 1) % len(self.buffer)
        return value

    # lcd x(graph height) 100 20ppm=1dot
    # lcd y(graph width)  100  1 sec=1dot
    def draw_graph(self, x, y, disp_mode_):
        global CO2_RED
        global CO2_YELLOW
        global DARK_RED
        global DARK_YELLOW
        global DARK_WHITE

        index_list = list(range(self.start, self.size)) +  list(range(0, self.end))
        index_list.reverse()
        for i in index_list:
            # set line color from co2 value
            val = self.buffer[index_list[i]]
            if val >= CO2_RED:
                col = DARK_RED
            elif val >= CO2_YELLOW:
                col = DARK_YELLOW
            else:
                col = DARK_WHITE

            # draw graph
            if disp_mode_ == 1:
                # co2_graph_data.draw_graph(100, 0, disp_mode)
                lcd.line(x - 100, y + i, x - 100 + int(val // 20), y + i, col)
            else:
                # co2_graph_data.draw_graph(35, 240, disp_mode)
                lcd.line(x + 100 - int(val //20), y-(self.size-i), x+100, y-(self.size-i), col)

        # red/yellow border lines
        lcd.font(lcd.FONT_DejaVu18, rotate=90)
        if disp_mode == 1:
            # red line
            lcd.print(str(CO2_RED), x - 100 + int(CO2_RED // 20) + 20, 5, DARK_RED)
            lcd.line(x - 100 + int(CO2_RED // 20), 0, x - 100 + int(CO2_RED // 20), 240, DARK_RED)
            # yellow line
            lcd.print(str(CO2_YELLOW), x - 100 + int(CO2_YELLOW // 20) + 20, 5, DARK_YELLOW)
            lcd.line(x - 100 + int(CO2_YELLOW // 20), 0, x - 100 + int(CO2_YELLOW // 20), 240, DARK_YELLOW)
        else:
            # red line
            lcd.line(x + 100 - int(CO2_RED // 20), 0, x + 100 - int(CO2_RED // 20), 240, DARK_RED)
            # yellow line
            lcd.line(x + 100 - int(CO2_YELLOW // 20), 0, x + 100 - int(CO2_YELLOW // 20), 240, DARK_YELLOW)



co2_graph_data = GraphData(240)


# @cinimlさんのファーム差分吸収ロジック
class AXPCompat(object):
    def __init__(self):
        if(hasattr(axp, 'setLDO2Vol')):
            self.setLDO2Vol = axp.setLDO2Vol
        else:
            self.setLDO2Vol = axp.setLDO2Volt


axp = AXPCompat()


# PWM用パルス関数
def pulse(length, time):
    for i in range(100):
        length.duty(int((math.sin(i / 50 * math.pi) * 50) + 50))
        utime.sleep_ms(time)


# LED PWMスレッド関数
def threadfunc_led_controller():
    global CO2_RED
    global co2

    # setup LED PWM
    frequency = 5000
    g10 = machine.PWM(machine.Pin(10), frequency)
    for i in range(3):
        g10.duty(0)
        utime.sleep_ms(100)
        g10.duty(100)
        utime.sleep_ms(100)

    while True:
        if co2 >= CO2_RED and not lcd_mute:
            pulse(g10, 10)
        else:
            g10.duty(100)
            utime.sleep_ms(100)


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
    global disp_mode
    if disp_mode == 1:
        disp_mode = 0
    else:
        disp_mode = 1

    draw()


def threadfunc_preheat_timer_count():
    global preheat_status
    global preheat_count
    global preheat_status_fc
    global preheat_status

    while True:
        if preheat_count > 0:
            preheat_status_fc = lcd.YELLOW
            preheat_status = "Preheating... " + str(preheat_count)
            preheat_count = preheat_count - 1
        else:
            preheat_status_fc = lcd.WHITE
            preheat_status = "OK"
            break

        utime.sleep_ms(1000)


# 表示モード切替時の枠描画処理関数
def draw():
    global disp_mode
    global lcd_mute
    global data_mute
    global CO2_RED
    global CO2_YELLOW
    global co2
    global co2_str
    global preheat_status
    global preheat_status_fc

    if data_mute or (co2 == 0):  # タイムアウトで表示ミュートされてるか、初期値のままならco2値非表示（灰文字化）
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

    # clear
    lcd.fillScreen(lcd.BLACK)

    if disp_mode == 1:  # 表示回転処理
        # draw graph
        co2_graph_data.draw_graph(100, 0, disp_mode)

        # status
        lcd.font(lcd.FONT_DejaVu18, rotate=90)
        lcd.print(preheat_status, 131, 30, preheat_status_fc)

        # line
        lcd.line(111, 0, 111, 240, lcd.LIGHTGREY)

        # "CO2 ppm" string
        lcd.font(lcd.FONT_DejaVu18, rotate=90)  # 単位(ppm)の表示
        lcd.print('CO2 ppm', 103, 130, fc)

        # CO2 value
        lcd.font(lcd.FONT_DejaVu72, rotate=90)  # co2値の表示
        co2_str_w = int(lcd.textWidth(co2_str))
        lcd.print(co2_str, 70, (210 - co2_str_w), fc)

    else:
        # draw graph
        co2_graph_data.draw_graph(35, 240, disp_mode)

        # status
        lcd.font(lcd.FONT_DejaVu18, rotate=270)
        lcd.print(preheat_status, 4, 210, preheat_status_fc)

        # line
        lcd.line(24, 0, 24, 240, lcd.LIGHTGREY)

        # "CO2 ppm" string
        lcd.font(lcd.FONT_DejaVu18, rotate=270)  # 単位(ppm)の表示
        lcd.print('CO2 ppm', 32, 110, fc)

        # CO2 value
        lcd.font(lcd.FONT_DejaVu72, rotate=0)  # co2値の表示
        co2_str_w = int(lcd.textWidth(co2_str))
        lcd.font(lcd.FONT_DejaVu72, rotate=270)  # co2値の表示
        # TODO: workaround lcd.print Y max 169.
        if (30 + co2_str_w) > 169:
            y_wa = 169
        else:
            y_wa = (10 + co2_str_w)
        lcd.print(co2_str, 65, y_wa, fc)


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
                if filetxt[0] == 'CO2_YELLOW':
                    if int(filetxt[1]) >= 1:
                        CO2_YELLOW = int(filetxt[1])
                        print('- CO2_YELLOW: ' + str(CO2_YELLOW))
                elif filetxt[0] == 'TIMEOUT':
                    if int(filetxt[1]) >= 1:
                        TIMEOUT = int(filetxt[1])
                        print('- TIMEOUT: ' + str(TIMEOUT))

    else:
        print('>> no [co2_set.txt] !')
    return scanfile_flg


# メインプログラムはここから（この上はプログラム内関数）


# 画面初期化
axp.setLDO2Vol(2.8)  # バックライト輝度調整（中くらい）

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

# preheatタイマー表示スレッド起動
_thread.start_new_thread(threadfunc_preheat_timer_count, ())

# 警告赤色LEDスレッド起動
_thread.start_new_thread(threadfunc_led_controller, ())

# メインルーチン（初期設定と描画ループ）
while True:
    if (utime.time() - co2_tc) >= co2_interval:  # co2要求コマンド送信
        mhz19b_data = bytearray(9)
        mhz19b.read()  # clear buffer
        mhz19b.write(b'\xff\x01\x86\x00\x00\x00\x00\x00\x79')   # co2測定値リクエスト
        utime.sleep_ms(100)
        mhz19b.readinto(mhz19b_data, len(mhz19b_data))
        # co2測定値リクエストの応答
        if mhz19b_data[0] == 0xff and mhz19b_data[1] == 0x86 and checksum_chk(
                mhz19b_data):    # 応答かどうかの判定とチェックサムチェック
            co2_tc = utime.time()
            co2 = mhz19b_data[2] * 256 + mhz19b_data[3]
            co2_graph_data.add(co2)
            data_mute = False
            draw()

    if (utime.time() - co2_tc) >= TIMEOUT:  # co2応答が一定時間無い場合はCO2値表示のみオフ
        data_mute = True
        draw()

    utime.sleep_ms(100)
    gc.collect()

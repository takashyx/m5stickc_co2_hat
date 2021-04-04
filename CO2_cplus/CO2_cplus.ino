#include <M5StickCPlus.h>
#include "MHZ19.h"
#include "Battery.h"

// Serial IF to MH-Z19C
const int RX_PIN = 26;           // Rx pin which the MHZ19 Tx pin is attached to
const int TX_PIN = 0;            // Tx pin which the MHZ19 Rx pin is attached to
const int BAUDRATE = 9600;       // Device to MH-Z19 Serial baudrate (should not be changed)
const int CO2_INTERVAL_MS = 500; // MH-19B or Cへco2測定値要求コマンドを送るサイクル（秒）
const int TIMEOUT_MS = 5000;     // 何らかの事情でCO2更新が止まった時のタイムアウト（秒）のデフォルト値
const int PREHEAT_SECONDS = 60;  // MH-Z19 preheat time 19B:180 19C:60

// Internal LED
const int LED_PIN = GPIO_NUM_10;
const int LED_PWMCH = 1;
const int LED_TASK_PRIORITY = 2;
const int LED_TASK_CORE = 0;
const int LED_CYCLE_TIME_MS = 1000;

// LCD settings
const int BRIGHTNESS = 10;
const int LCD_WIDTH = 240;
const int LCD_HEIGHT = 135;

// CO2 graph settings
const int CO2_RED_BORDER = 1500;    // co2濃度の赤色閾値（ppm） LEDも点滅
const int CO2_YELLOW_BORDER = 1000; //co2濃度の黄色閾値（ppm）

#define DARK_RED M5.Lcd.color565(111, 0, 0)
#define DARKER_RED M5.Lcd.color565(95, 0, 0)
#define DARK_YELLOW M5.Lcd.color565(95, 95, 0)
#define DARKER_YELLOW M5.Lcd.color565(47, 47, 0)
#define DARK_WHITE M5.Lcd.color565(63, 63, 63)

const bool dummy_data_mode = false;

MHZ19 myMHZ19;              // Constructor for library
HardwareSerial mySerial(1); // (ESP32 Example) create device to MH-Z19 serial

int preheat_remaining_ms = PREHEAT_SECONDS * 1000;
unsigned long getDataTimer = 0;

bool led_on_status = false;
bool lcd_on_status = false;

int history[LCD_WIDTH] = {};
int historyPos = 0;

TFT_eSprite framebuf = TFT_eSprite(&M5.Lcd);

void setup()
{
    // init
    M5.begin();

    // LED
    pinMode(LED_PIN, OUTPUT);
    ledcSetup(LED_PWMCH, 12000, 8);
    ledcAttachPin(LED_PIN, LED_PWMCH);
    ledcWrite(LED_PWMCH, 256);

    // Display
    M5.Axp.ScreenBreath(BRIGHTNESS);

    // スプライト範囲の作成
    framebuf.setColorDepth(10);
    framebuf.createSprite(LCD_WIDTH, LCD_HEIGHT);
    // カーソル移動
    framebuf.setCursor(0, 0);
    framebuf.setTextSize(1);

    // serial start
    Serial.begin(9600);                                   // Device to serial monitor feedback
    mySerial.begin(BAUDRATE, SERIAL_8N1, RX_PIN, TX_PIN); // (ESP32 Example) device to MH-Z19 serial start
    myMHZ19.begin(mySerial);                              // *Serial(Stream) refence must be passed to library begin().
    myMHZ19.autoCalibration(true);

    M5.Lcd.setRotation(3);
    render();

    if (dummy_data_mode)
    {
        int speed_multiple = 5;
        for (int i = 0; i < LCD_WIDTH; i++)
        {
            history[i] = int(sin(speed_multiple * 2 * PI * i / LCD_WIDTH) * 500) + 1250;
        }
    }

    Serial.println("setup end!");

    xTaskCreatePinnedToCore(led_controller_task, "ledController", 4096, NULL, LED_TASK_PRIORITY, NULL, LED_TASK_CORE);
}

void drawBattery(int x, int y, int w, int h)
{
    auto battery_frame_color = WHITE;
    auto battery_string_color = WHITE;
    auto battery_bg_color = BLACK;
    const int tokki = 4;

    auto battery_color = DARKER_YELLOW;
    if (!isUsingBattery())
    {
        battery_color = BLUE;
    }
    else if (isLowBattery())
    {
        battery_color = RED;
    }

    int percent = calcBatteryPercent();
    int battery_level_width = w * percent / 100;

    // background
    framebuf.fillRect(x, y, w - tokki, h, battery_bg_color);
    framebuf.fillRect(x + w - tokki - 1, y + (h / 4), tokki, h / 2, battery_bg_color);
    framebuf.drawRect(x, y, w - tokki, h, battery_frame_color);
    framebuf.drawRect(x + w - tokki - 1, y + (h / 4), tokki, h / 2, battery_frame_color);
    framebuf.drawFastVLine(x + w - tokki - 1, y + (h / 4) + 1, (h / 2) - 2, battery_bg_color);

    // gauge
    framebuf.fillRect(x + 1, y + 1, min(w - tokki - 2, battery_level_width - 1), h - 2, battery_color);
    if (battery_level_width - 1 > w - tokki - 2)
    {
        framebuf.fillRect(x + w - tokki - 1, y + (h / 4) + 1,
                          battery_level_width - (w - tokki) - 1, (h / 2) - 2, battery_color);
    }

    // text
    framebuf.setTextColor(battery_string_color);
    framebuf.drawCentreString(String(percent) + "%", x + (w / 2) - (tokki / 2), y + (h / 2) - 8, 2);
}

void loop()
{
    auto now = millis();
    if (now - getDataTimer >= CO2_INTERVAL_MS)
    {
        /* note: getCO2() default is command "CO2 Unlimited". This returns the correct CO2 reading even
      if below background CO2 levels or above range (useful to validate sensor). You can use the
      usual documented command with getCO2(false) */

        int CO2 = myMHZ19.getCO2();                        // Request CO2 (as ppm)
        int8_t temp = myMHZ19.getTemperature(false, true); // Request Temperature (as Celsius)

        Serial.print("CO2 (ppm): ");
        Serial.print(CO2);
        Serial.print(", Temperature (C): ");
        Serial.println(temp);

        // ledOn = CO2 >= 1200;

        // 測定結果の表示
        historyPos = (historyPos + 1) % (sizeof(history) / sizeof(int));
        if (dummy_data_mode == false)
            history[historyPos] = CO2;
        render();

        if (preheat_remaining_ms > 0)
        {
            preheat_remaining_ms -= (now - getDataTimer);
        }
        getDataTimer = now;
    }
}

void render()
{
    M5.update();

    // front button to on/off LCD
    if (M5.BtnA.wasPressed())
    {
        lcd_on_status = !lcd_on_status;
        if (lcd_on_status == true)
        {
            M5.Axp.ScreenBreath(BRIGHTNESS);
            Serial.println("turned LCD on");
        }
        else
        {
            M5.Axp.ScreenBreath(0);
            Serial.println("turned LCD off");
        }
    }

    // Clear
    framebuf.fillSprite(BLACK);

    // graph
    int len = sizeof(history) / sizeof(int);
    auto graph_col = DARK_WHITE;

    for (int i = 0; i < len; i++)
    {
        auto value = max(0, history[(historyPos + 1 + i) % len]);
        if (value > CO2_RED_BORDER)
            graph_col = DARK_RED;
        else if (value > CO2_YELLOW_BORDER)
            graph_col = DARK_YELLOW;
        else
            graph_col = DARK_WHITE;

        auto value_height = min(LCD_HEIGHT, (int)(value / 20));
        framebuf.drawFastVLine(i, LCD_HEIGHT - value_height, value_height, graph_col);
    }

    // status line
    framebuf.drawFastHLine(0, 25, 240, WHITE);

    // border lines
    framebuf.drawFastHLine(0, LCD_HEIGHT - (CO2_RED_BORDER / 20), 240, DARKER_RED);
    framebuf.drawFastHLine(0, LCD_HEIGHT - (CO2_YELLOW_BORDER / 20), 240, DARKER_YELLOW);

    // border fonts
    framebuf.setTextColor(DARKER_RED);
    framebuf.drawString(String(CO2_RED_BORDER), 2, LCD_HEIGHT - (CO2_RED_BORDER / 20) - 22, 4);
    framebuf.setTextColor(DARKER_YELLOW);
    framebuf.drawString(String(CO2_YELLOW_BORDER), 2, LCD_HEIGHT - (CO2_YELLOW_BORDER / 20) - 22, 4);

    //texts
    // ppm
    auto co2_value = history[historyPos];
    auto status_col = WHITE;
    auto status_text = "OK";

    if (co2_value >= CO2_RED_BORDER)
    {
        status_col = RED;
        status_text = "DANGER";
        led_on_status = true;
    }
    else if (co2_value >= CO2_YELLOW_BORDER)
    {
        status_col = YELLOW;
        status_text = "WARNING";
        led_on_status = false;
    }
    else
    {
        led_on_status = false;
    }
    // status
    framebuf.setTextColor(status_col);
    framebuf.drawString(status_text, 3, 3, 4);

    if (preheat_remaining_ms > 0)
    {
        framebuf.setTextColor(YELLOW);
        framebuf.drawRightString("init... " + String(int(preheat_remaining_ms / 1000)), LCD_WIDTH - 60, 5, 2);
    }

    framebuf.setTextColor(status_col);
    framebuf.drawRightString("CO2 ppm", LCD_WIDTH - 12, 30, 4);
    framebuf.drawRightString(String(co2_value), LCD_WIDTH - 8, 55, 8);

    // Battery Status
    drawBattery(185, 5, 50, 16);

    // push to LCD
    framebuf.pushSprite(0, 0);
}

void led_controller_task(void *p)
{

    for (int i = 0; i < 3; i++)
    {
        delay(100);
        ledcWrite(LED_PWMCH, 0);
        delay(100);
        ledcWrite(LED_PWMCH, 256);
    }

    auto ts = millis();
    auto last_ts = ts;
    int val = 0;
    int phase_ms = 0;

    while (1)
    {
        ts = millis();
        if (led_on_status)
        {
            phase_ms = (phase_ms + (ts - last_ts)) % LED_CYCLE_TIME_MS;
            int val = int(sin(2 * PI * phase_ms / LED_CYCLE_TIME_MS) * 128) + 128;
            ledcWrite(LED_PWMCH, val);
            last_ts = ts;
            delay(10);
        }
        else
        {
            ledcWrite(LED_PWMCH, 256);
            delay(10);
        }
    }
}
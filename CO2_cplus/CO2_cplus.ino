#include <M5StickCPlus.h>
#include "MHZ19.h"

// Serial IF to MH-Z19C
#define RX_PIN 26           // Rx pin which the MHZ19 Tx pin is attached to
#define TX_PIN 0            // Tx pin which the MHZ19 Rx pin is attached to
#define BAUDRATE 9600       // Device to MH-Z19 Serial baudrate (should not be changed)
#define CO2_INTERVAL_MS 500 // MH-19B or Cへco2測定値要求コマンドを送るサイクル（秒）
#define TIMEOUT_MS 5000     // 何らかの事情でCO2更新が止まった時のタイムアウト（秒）のデフォルト値
#define PREHEAT_SECONDS 60  // MH-Z19 preheat time 19B:180 19C:60

// LCD settings
#define BRIGHTNESS 10
#define LCD_WIDTH 240
#define LCD_HEIGHT 135

// CO2 graph settings
#define CO2_RED_BORDER 1500    // co2濃度の赤色閾値（ppm） LEDも点滅
#define CO2_YELLOW_BORDER 1000 //co2濃度の黄色閾値（ppm）

#define DARK_RED M5.Lcd.color565(111, 0, 0)
#define DARKER_RED M5.Lcd.color565(79, 0, 0)
#define DARK_YELLOW M5.Lcd.color565(95, 95, 0)
#define DARKER_YELLOW M5.Lcd.color565(47, 47, 0)
#define DARK_WHITE M5.Lcd.color565(63, 63, 63)

MHZ19 myMHZ19;              // Constructor for library
HardwareSerial mySerial(1); // (ESP32 Example) create device to MH-Z19 serial

int preheat_remaining_ms = PREHEAT_SECONDS * 1000;

unsigned long getDataTimer = 0;

int history[240] = {};
int historyPos = 0;

TFT_eSprite framebuf = TFT_eSprite(&M5.Lcd);

void setup()
{
    // init
    M5.begin();
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

    // setup internal red LED
    // pinMode(GPIO_NUM_10, OUTPUT);
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
    framebuf.drawString(String(CO2_RED_BORDER), 5, LCD_HEIGHT - (CO2_RED_BORDER / 20) - 20, 4);
    framebuf.setTextColor(DARKER_YELLOW);
    framebuf.drawString(String(CO2_YELLOW_BORDER), 5, LCD_HEIGHT - (CO2_YELLOW_BORDER / 20) - 20, 4);

    //texts
    // ppm
    auto co2_value = history[historyPos];
    auto status_col = WHITE;
    auto status_text = "OK";
    if (co2_value >= CO2_RED_BORDER)
    {
        status_col = RED;
        status_text = "DANGER";
    }
    else if (co2_value > CO2_YELLOW_BORDER)
    {
        status_col = YELLOW;
        status_text = "WARNING";
    }
    // status
    framebuf.setTextColor(status_col);
    framebuf.drawString(status_text, 3, 3, 4);

    if (preheat_remaining_ms > 0)
    {
        framebuf.setTextColor(YELLOW);
        framebuf.drawRightString("Preheating... " + String(int(preheat_remaining_ms / 1000)), LCD_WIDTH - 8, 5, 2);
    }

    framebuf.setTextColor(status_col);
    framebuf.drawRightString("CO2 ppm", LCD_WIDTH - 12, 30, 4);
    framebuf.drawRightString(String(co2_value), LCD_WIDTH - 8, 55, 8);

    // push to LCD
    framebuf.pushSprite(0, 0);
}
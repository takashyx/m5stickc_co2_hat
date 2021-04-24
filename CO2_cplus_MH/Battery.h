/**
 * 電池残量表示
 */
#include <M5StickCPlus.h>

const float MAX_BATTERY_VOLTAGE = 4.2f;
const float MIN_BATTERY_VOLTAGE = 3.0f;
/**
 * バッテリー残量%を計算する関数(戻り値は0～100)
 */
int calcBatteryPercent()
{
    float _vbat = M5.Axp.GetBatVoltage();
    float ratio = (_vbat - MIN_BATTERY_VOLTAGE) / (MAX_BATTERY_VOLTAGE - MIN_BATTERY_VOLTAGE);
    return roundf((ratio * 100.0f) + 0.5f);
}

/**
 * 低電圧状態かを判定する関数
 */
bool isLowBattery()
{
    // 低電圧状態(3.4V以下)だと1それ以外は0
    uint8_t _low_bat = M5.Axp.GetWarningLeve();
    if (_low_bat == 0)
    {
        return false;
    }
    else
    {
        return true;
    }
}

/**
 * バッテリー稼働か充電中かを判定する関数
 */
bool isUsingBattery()
{
    // プラスが充電、マイナスがバッテリー稼働
    float _ibat = M5.Axp.GetBatCurrent();
    if (_ibat < 0.0f)
    {
        return true;
    }
    else
    {
        return false;
    }
}

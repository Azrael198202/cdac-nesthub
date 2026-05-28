from typing import List
import requests

def get_weather(city_name: List[str], date_str: List[str] = None):
    city_name_items = city_name if isinstance(city_name, list) else ([city_name] if city_name is not None else [None])
    date_str_items = date_str if isinstance(date_str, list) else ([date_str] if date_str is not None else [None])
    for one_city_name in city_name_items:
        for one_date_str in date_str_items:
            _get_weather_single(one_city_name, one_date_str)

def _get_weather_single(city_name, date_str=None):
    api_key = "dc9fb102c13b4b958f981339262205"
    
    if date_str:
        url = "https://api.weatherapi.com/v1/forecast.json"
        params = {
            "key": api_key,
            "q": city_name,
            "dt": date_str,
            "lang": "zh"
        }
    else:
        url = "https://api.weatherapi.com/v1/current.json"
        params = {
            "key": api_key,
            "q": city_name,
            "lang": "zh"
        }

    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if "error" in data:
            print(f"❌ 错误: {data['error']['message']}")
            return

        if not date_str:
            location = data["location"]["name"]
            temp = data["current"]["temp_c"]
            condition = data["current"]["condition"]["text"]
            print(f"🌍 城市: {location} | 🌡️ 实时温度: {temp}°C | ☁️ 天气: {condition}")
        
        else:
            location = data["location"]["name"]
            day_data = data["forecast"]["forecastday"][0]["day"]
            max_temp = day_data["maxtemp_c"]
            min_temp = day_data["mintemp_c"]
            condition = day_data["condition"]["text"]
            print(f"🌍 城市: {location} | 📅 日期: {date_str} | 🌡️ 最高温: {max_temp}°C | 📉 最低温: {min_temp}°C | ☁️ 天气: {condition}")

    except Exception as e:
        print(f"网络请求失败: {e}")
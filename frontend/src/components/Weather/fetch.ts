import { Aqi, FirstQuarter, FullMoon, Humidity, LastQuarter, NewMoon, Pressure, Sunrise, Sunset, Uvi, Visibility, WaningCrescent, WaningGibbous, WaxingCrescent, WaxingGibbous, WeatherIcons, Wind } from './icons';
import type { Day, DataPoint, DailyForecastData, AirQualityData, WeatherData, HourlyForecastData, CurrentWeather, ParsedWeatherData, LocationData } from './types';
import { Units } from './types';
import { fetchWeatherApi } from 'openmeteo';
import { formatTime, mapWmoToOwmIconCode } from './utils';
import { format } from 'date-fns';

export const getParsedWeatherData = async (lat: string, long: string, api_key: string): Promise<ParsedWeatherData> => {
    const location = await getLocation(lat, long, api_key);
    const current = await getCurrentWeather(lat, long);
    const hourly = await getHourlyForecast(lat, long);
    const daily = await getDailyForecast(lat, long);
    const aqiData = await getAirQuality(lat, long);
    const weatherData: WeatherData = {
        current,
        daily,
        hourly,
    }
    const parsed = await parseWeatherData(weatherData, aqiData, location);
    return parsed;
}

const getLocation = async (lat: string, long: string, api_key: string): Promise<LocationData> => {
    const response = await fetch(`https://api.openweathermap.org/geo/1.0/reverse?lat=${lat}&lon=${long}&limit=1&appid=${api_key}`);
    const resultData = await response.json();
    return resultData[0];
}

const parseWeatherData = async (weatherData: WeatherData, aqiData: AirQualityData, locationData: LocationData, units: string = "imperial", timeFormat: '12h' | '24h' = '12h'): Promise<ParsedWeatherData> => {
    const current = weatherData.current;
    const dt = current.time;
    const currentIcon = WeatherIcons[mapWmoToOwmIconCode(current.weatherCode)];
    const locationStr = `${locationData.name}, ${locationData.state || locationData.country}`;

    return {
        currentDate: format(dt, "EEEE, MMMM d"),
        location: locationStr,
        currentDayIcon: currentIcon,
        currentTemperature: Number(current.temperature).toFixed(0),
        feelsLike: Number(current.feelsLike).toFixed(0),
        temperatureUnit: Units[units].temperature,
        units: units,
        timeFormat: timeFormat,
        forecast: parseForecast(weatherData.daily),
        dataPoints: parseDataPoints(weatherData, aqiData, units, timeFormat),
        hourlyForecast: weatherData.hourly,
    };
}

const choosePhaseIcon = (phase: number): any => {
    const PHASES = [
        { value: 0.0, name: NewMoon },
        { value: 0.25, name: FirstQuarter },
        { value: 0.5, name: FullMoon },
        { value: 0.75, name: LastQuarter },
        { value: 1.0, name: NewMoon }, // API treats 1.0 same as 0.0
    ];

    // Check for exact matches
    for (const p of PHASES) {
        if (Math.abs(phase - p.value) < 0.001) {
            return p.name;
        }
    }

    // Check for intermediate phases
    if (phase > 0.0 && phase < 0.25) {
        return WaxingCrescent;
    } else if (phase > 0.25 && phase < 0.5) {
        return WaxingGibbous;
    } else if (phase > 0.5 && phase < 0.75) {
        return WaningGibbous;
    } else { // 0.75 < phase < 1.0
        return WaningCrescent;
    }
}

const parseForecast = (dailyForecast: DailyForecastData[]): Day[] => {
    const forecast = [];

    // Skip today's forecast (index 0) and process the rest.
    for (const day of dailyForecast.slice(1)) {
        // --- Weather Icon ---
        const weatherIconPath = WeatherIcons[mapWmoToOwmIconCode(day.weatherCode)];

        // --- Moon Phase & Icon ---
        const moonPhase = 0.0; // TODO: fetch moonphase info
        const moonIconPath = choosePhaseIcon(moonPhase);

        // --- True illumination percent, formatted with no decimals ---
        const illumFraction = (1 - Math.cos(2 * Math.PI * moonPhase)) / 2;
        const moonPct = (illumFraction * 100).toFixed(0);

        // --- Date & Temps ---
        const dayLabel = format(day.time, "eee"); // Abbreviated day name, e.g., "Mon"

        forecast.push({
            day: dayLabel,
            high: day.maxTemp,
            low: day.minTemp,
            icon: weatherIconPath,
            moonPhasePercent: moonPct,
            moonPhaseIcon: moonIconPath,
        });
    }

    return forecast;
}

const parseDataPoints = (weather: WeatherData, airQuality: AirQualityData, units: string, timeFormat: '12h' | '24h'): DataPoint[] => {
    const dataPoints: DataPoint[] = [];
    const current = weather.current || {};

    const { sunrise, sunset } = current;

    if (sunrise) {
        const { time, unit } = formatTime(sunrise, timeFormat);
        dataPoints.push({
            label: "Sunrise",
            measurement: time,
            unit: unit,
            icon: Sunrise,
        });
    } else {
        console.error("Sunrise not found in OpenWeatherMap response; this is expected for polar areas.");
    }

    if (sunset) {
        const { time, unit } = formatTime(sunset, timeFormat);
        dataPoints.push({
            label: "Sunset",
            measurement: time,
            unit: unit,
            icon: Sunset,
        });
    } else {
        console.error("Sunset not found in OpenWeatherMap response; this is expected for polar areas.");
    }

    dataPoints.push({
        label: "Wind",
        measurement: Number(current.windSpeed).toFixed(1),
        unit: Units[units].speed,
        icon: Wind,
    });

    dataPoints.push({
        label: "Humidity",
        measurement: String(Math.round(current.humidity)),
        unit: '%',
        icon: Humidity,
    });

    dataPoints.push({
        label: "Pressure",
        measurement: String(Math.round(current.pressure)),
        unit: 'hPa',
        icon: Pressure,
    });

    dataPoints.push({
        label: "UV Index",
        measurement: Number(current.uvIndex).toFixed(1),
        unit: '',
        icon: Uvi,
    });

    const visibility = current.visibility / 5280;
    const visibilityStr = visibility >= 10 ? `>10` : Number(visibility).toFixed(1);
    dataPoints.push({
        label: "Visibility",
        measurement: visibilityStr,
        unit: 'mi',
        icon: Visibility,
    });

    const aqi = airQuality?.usAqi;
    if (aqi) {
        dataPoints.push({
            label: "Air Quality",
            measurement: String(Math.round(aqi)),
            unit: getAqiLabel(aqi),
            icon: Aqi,
        });
    }

    return dataPoints;
}

const aqiLabels = [
    "Good",
    "Fair",
    "Moderate",
    "Poor",
    "Very Poor",
    "Hazardous"
];

function getAqiLabel(aqi: number): string {
    if (aqi <= 50) return aqiLabels[0];
    if (aqi <= 100) return aqiLabels[1];
    if (aqi <= 150) return aqiLabels[2];
    if (aqi <= 200) return aqiLabels[3];
    if (aqi <= 300) return aqiLabels[4];
    return aqiLabels[5];
}

// hourly:
// https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${long}&hourly=temperature_2m,precipitation_probability&timezone=auto
// current:
// https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${long}&daily=uv_index_max,sunset,sunrise,apparent_temperature_max,apparent_temperature_min&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,surface_pressure,wind_speed_10m&timezone=auto&forecast_days=1&timeformat=unixtime&wind_speed_unit=mph&temperature_unit=fahrenheit&precipitation_unit=inch
// daily:
// https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${long}&daily=apparent_temperature_max,apparent_temperature_min,weather_code&timezone=auto&timeformat=unixtime&wind_speed_unit=mph&temperature_unit=fahrenheit&precipitation_unit=inch

const METEO_URL = "https://api.open-meteo.com/v1/forecast";
const METEO_AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality";

const METEO_OPTIONS = {
    "timezone": "auto",
    "timeformat": "unixtime",
    "wind_speed_unit": "mph",
    "temperature_unit": "fahrenheit",
    "precipitation_unit": "inch"
}

const getDailyForecast = async (lat: string, long: string): Promise<DailyForecastData[]> => {
    const params = {
        "latitude": lat,
        "longitude": long,
        "daily": ["apparent_temperature_max", "apparent_temperature_min", "weather_code"],
        "forecast_days": 7,
        ...METEO_OPTIONS
    };
    const responses = await fetchWeatherApi(METEO_URL, params);
    const response = responses[0];
    const daily = response.daily()!;

    return [...Array((Number(daily.timeEnd()) - Number(daily.time())) / daily.interval())].map(
        (_, i) => {
            return {
                time: new Date((Number(daily.time()) + i * daily.interval()) * 1000),
                maxTemp: daily.variables(0)!.values(i)!,
                minTemp: daily.variables(1)!.values(i)!,
                weatherCode: daily.variables(2)!.values(i)!,
            }
        });

}

const getHourlyForecast = async (lat: string, long: string): Promise<HourlyForecastData[]> => {
    const params = {
        "latitude": lat,
        "longitude": long,
        "hourly": ["temperature_2m", "precipitation_probability"],
        "forecast_days": 1,
        ...METEO_OPTIONS
    };
    const responses = await fetchWeatherApi(METEO_URL, params);
    const response = responses[0];
    const hourly = response.hourly()!;

    return [...Array((Number(hourly.timeEnd()) - Number(hourly.time())) / hourly.interval())].map(
        (_, i) => {
            return {
                time: new Date((Number(hourly.time()) + i * hourly.interval()) * 1000),
                temperature: hourly.variables(0)!.values(i)!,
                precipitation: hourly.variables(1)!.values(i)!,
            };
        });
}

const getAirQuality = async (lat: string, long: string): Promise<AirQualityData> => {
    const params = {
        "latitude": lat,
        "longitude": long,
        "current": ["us_aqi"],
        "forecast_days": 1,
        ...METEO_OPTIONS
    };
    const responses = await fetchWeatherApi(METEO_AQI_URL, params);
    const response = responses[0];
    const current = response.current()!;
    return {
        usAqi: Math.round(current.variables(0)!.value()),
    };
}

const getCurrentWeather = async (lat: string, long: string): Promise<CurrentWeather> => {
    const params = {
        "latitude": lat,
        "longitude": long,
        "daily": ["uv_index_max", "sunset", "sunrise", "apparent_temperature_max", "apparent_temperature_min"],
        "current": ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "weather_code", "surface_pressure", "wind_speed_10m", "visibility"],
        "forecast_days": 1,
        ...METEO_OPTIONS
    };
    const responses = await fetchWeatherApi(METEO_URL, params);
    const response = responses[0];
    const current = response.current()!;
    const daily = response.daily()!;

    const sunset = daily.variables(1)!;
    const sunrise = daily.variables(2)!;

    // Note: The order of weather variables in the URL query and the indices below need to match!
    return {
        time: new Date((Number(current.time())) * 1000),
        temperature: Number(current.variables(0)!.value()),
        feelsLike: Number(current.variables(2)!.value()),
        humidity: current.variables(1)!.value(),
        weatherCode: Number(current.variables(3)!.value()),
        pressure: Number(current.variables(4)!.value()),
        windSpeed: Number(current.variables(5)!.value()),
        sunrise: new Date((Number(sunrise.valuesInt64(0))) * 1000),
        sunset: new Date((Number(sunset.valuesInt64(0))) * 1000),
        uvIndex: Number(daily.variables(0)!.values(0)!),
        maxTemp: Math.round(daily.variables(3)!.values(0)!),
        minTemp: Math.round(daily.variables(4)!.values(0)!),
        visibility: Math.round(current.variables(6)!.value()),
    };
}

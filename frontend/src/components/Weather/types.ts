export interface Day {
    day: string;
    icon: any;
    high: number;
    low: number;
    moonPhaseIcon: any;
    moonPhasePercent: string;
}

export interface DataPoint {
    label: string;
    measurement: string;
    unit: string;
    icon: string;
}

export interface LocalWeather {
    currentTemp: string;
    temperatureUnit: string;
    feelsLike: string;
    units: "standard" | "nonstandard";
}

export interface ParsedWeatherData {
    currentDate: string;
    location: string;
    currentDayIcon: any;
    currentTemperature: string;
    feelsLike: string;
    temperatureUnit: string;
    units: string;
    timeFormat: "12h" | "24h";
    forecast: Day[];
    dataPoints: DataPoint[];
    hourlyForecast: HourlyForecastData[];
}

export interface DailyForecastData {
    time: Date;
    weatherCode: number;
    minTemp: number;
    maxTemp: number;
}

export interface AirQualityData {
    usAqi: number;
}

export interface HourlyForecastData {
    time: Date;
    temperature: number;
    precipitation: number;
}

export interface WeatherData {
    current: CurrentWeather;
    daily: DailyForecastData[];
    hourly: HourlyForecastData[];
}

export interface CurrentWeather {
    time: Date;
    sunrise?: Date;
    sunset?: Date;
    windSpeed: number;
    humidity: number;
    pressure: number;
    uvIndex: number;
    visibility: number;
    weatherCode: number;
    temperature: number;
    feelsLike: number;
    minTemp: number;
    maxTemp: number;
}

interface Unit {
    temperature: string,
    speed: string,
}

export const Units: { [id: string]: Unit } = {
    standard: {
        temperature: "K",
        speed: "m/s",
    },
    metric: {
        temperature: "°C",
        speed: "m/s",
    },
    imperial: {
        temperature: "°F",
        speed: "mph",
    },
};

export interface ApiKey {
    api_key: string,
}

export interface Units {
    units: string,
}

export interface Latitude {
    lat: string,
    long: string,
};

export interface LocationData {
    name: string;
    lat: number;
    lon: number;
    country: string;
    state?: string;
}

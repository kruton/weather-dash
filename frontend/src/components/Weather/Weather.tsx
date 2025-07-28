import { useEffect, useState } from 'react';
import { useQueryState } from 'nuqs';
import styles from './weather.module.css';
import './main.css';
import { HourlyGraph } from './chart';
import type { Day, DataPoint, ParsedWeatherData } from './types';
import { getParsedWeatherData } from './fetch';
import { format } from 'date-fns';

const SHOW_LAST_REFRESH = false;
const DISPLAY_METRICS = true;
const DISPLAY_HOURLY_GRAPH = true;
const DISPLAY_FORECAST = true;
const SHOW_MOON_PHASE = false;

const LastRefresh = () => {
    if (!SHOW_LAST_REFRESH) return;

    const now = format(new Date(), "EEEE, MMMM d")
    return (
        <div className={styles["last-refresh"]}>Last refresh: {now}</div>
    );
}

const Header = ({ cityName }: { cityName: string }) => {
    const current_date = format(new Date(), "EEEE, MMMM d");
    return (
        <div className={styles.header}>
            <div className={styles.location}>{cityName}</div>
            <div className={styles["current-date"]}>{current_date}</div>
        </div>
    );
}

const CurrentWeather = ({ current }: { current: ParsedWeatherData }) => {
    return (
        <div className={styles["current-temperature"]}>
            <img className={styles["current-icon"]} src={current.currentDayIcon} alt="Current Weather Icon" />
            <div className={styles["current-weather"]}>
                <div className={styles["current-temp"]}>{current.currentTemperature}<span className={styles["temperature-unit"]}>{current.temperatureUnit}</span></div>
                <div className={styles["feels-like"]}>Feels Like {current.feelsLike}{current.units != "standard" ? "°" : ""}</div>
            </div>
        </div>
    );
}

const Today = ({ current }: { current: ParsedWeatherData }) => {
    return (
        <div className={styles["today-container"]}>
            <CurrentWeather current={current} />
            {DISPLAY_METRICS ? (<Metrics dataPoints={current.dataPoints} />) : ""}
        </div>
    );
}

const DataPoint = ({ dp }: { dp: DataPoint }) => {
    return (
        <div className={[styles["data-point"], styles["column-container"]].join(' ')}>
            <div className={styles["data-point-img-container"]}>
                <img className={styles["data-point-icon"]} src={dp.icon} alt={dp.label} />
            </div>
            <div className={styles["data-point-data"]}>
                <div className={styles["data-point-label"]}>{dp.label}</div>
                <div className={styles["data-point-measurement"]}>
                    {dp.measurement}
                    {dp.unit ? (<span className={styles["data-point-unit"]}>{dp.unit}</span>) : ""}
                </div>
            </div>
        </div>
    );
}

const Metrics = ({ dataPoints }: { dataPoints: DataPoint[] }) => {
    return (
        <div className={styles["data-points"]}>
            {dataPoints.map((dp, index) => (
                <DataPoint key={index} dp={dp} />
            ))}
        </div>
    );
}

const MoonPhase = ({ day }: { day: Day }) => (
    <div className={styles["moon-phase-container"]}>
        <img className={styles["moon-phase-icon"]} src={day.moonPhaseIcon} alt="Moon phase icon" />
        <span style={{ flex: 1 }}>{day.moonPhasePercent} %</span>
    </div>
);

const ForecastDay = ({ day, units }: { day: Day, units: string }) => {
    const unitSuffix = units != "standard" ? "°" : "";

    return (
        <div className={styles["forecast-day"]}>
            <div className={styles["forecast-day-name"]}>{day.day}</div>
            <img className={styles["forecast-icon"]} src={day.icon} alt={day.day + " Weather Icon"} />
            <div className={styles["forecast-temps"]}>
                <span className={styles.high}>{Math.round(day.high)}{unitSuffix}</span>{' / '}
                <span className={styles.low}>{Math.round(day.low)}{unitSuffix}</span>
            </div>
            {SHOW_MOON_PHASE ? (
                <div>
                    <div className={styles.separator} />
                    <MoonPhase day={day} />
                </div>
            ) : ""}
        </div>
    );
}

const Forecast = ({ days, units }: { days: Day[], units: string }) => (
    <div className={styles.forecast}>
        {days.map((day, index) => (
            <ForecastDay key={index} day={day} units={units} />
        ))}
    </div>
);

const Weather = () => {
    const [lat] = useQueryState("lat", { defaultValue: "37.7749" });
    const [long] = useQueryState("long", { defaultValue: "-122.4194" });
    const [name] = useQueryState("name");
    const [weatherData, setWeatherData] = useState<ParsedWeatherData>();

    useEffect(() => {
        console.log(`trying to fetch... for ${lat} and ${long}`);
        getParsedWeatherData(name, lat, long).then(response => setWeatherData(response));
    }, [name, lat, long]);

    if (weatherData == null) { return (<div>Loading...</div>); }

    return (
        <div className={styles["weather-dashboard"]} style={{ padding: `1.5vw` }}>
            <link rel="preconnect" href="https://fonts.googleapis.com" />
            <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
            <link href="https://fonts.googleapis.com/css2?family=Jost:ital,wght@0,100..900;1,100..900&family=Tiny5&display=swap" rel="stylesheet" />
            <LastRefresh />
            <Header cityName={weatherData.location} />
            <Today current={weatherData} />
            {DISPLAY_HOURLY_GRAPH ? (<HourlyGraph hours={weatherData.hourlyForecast} />) : ""}
            {DISPLAY_FORECAST ? (<Forecast days={weatherData.forecast} units={weatherData.units} />) : ""}
        </div>
    );
}

export default Weather;

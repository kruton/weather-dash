import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    Filler,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    LineController,
    BarController,
} from 'chart.js';
import { format } from 'date-fns';
import type { ChartOptions } from 'chart.js';
import { Chart } from 'react-chartjs-2';
import styles from './weather.module.css';
import type { HourlyForecastData } from './types';

ChartJS.register(
    CategoryScale,
    BarElement,
    LinearScale,
    PointElement,
    LineElement,
    Filler,
    Title,
    Tooltip,
    Legend,
    LineController,
    BarController
);

export const HourlyGraph = ({ hours }: { hours: HourlyForecastData[] }) => {
    const temperatures = hours.map(x => x.temperature);
    const precipitation = hours.map(x => x.precipitation);
    const labels = hours.map(x => format(x.time, 'h a'))

    const minTemp = Math.round(Math.min(...temperatures));
    const maxTemp = Math.round(Math.max(...temperatures));
    const tempPadding = Math.min(1, Math.ceil((maxTemp - minTemp) * 0.1));

    const options: ChartOptions = {
        animation: {
            duration: 0, // general animation time
        },
        responsive: true,
        maintainAspectRatio: false,
        scales: {
            x: {
                ticks: {
                    autoSkip: true,
                    padding: 0,
                    maxRotation: 0, // Prevent label rotation
                    minRotation: 0, // Prevent label rotation
                    color: "black",
                    font: {
                        family: 'Jost',
                        size: 14,
                    }
                },
                grid: {
                    tickLength: 0,
                    display: false // Hide x-axis grid
                },
                offset: true,
            },
            y: {
                ticks: {
                    padding: 0,
                    color: "black",
                    font: {
                        family: 'Jost',
                        size: 14,
                    },
                    autoSkip: false,
                    callback: function (_, index, values) {
                        if (index === values.length - 1) return maxTemp + "°";
                        else if (index === 0) return minTemp + "°";
                        else return '';
                    }
                },
                grid: { display: false },
                min: minTemp - tempPadding,
                max: maxTemp + tempPadding,
            },
            y1: {
                position: 'right',
                grid: { display: false },
                ticks: {
                    padding: 0,
                    color: "black",
                    font: {
                        family: 'Jost',
                        size: 14,
                    },
                    autoSkip: false,
                    callback: function (_, index, values) {
                        if (index === values.length - 1) return "100%";
                        else if (index === 0) return "0%";
                        else return '';
                    }
                },
                min: 0,
                max: 100,
            }
        },
        plugins: { legend: { display: false } }, // Hide legend
        elements: {
            line: {
                borderJoinStyle: 'round' // Smoother line connection
            }
        }
    };

    const data = {
        labels,
        datasets: [
            {
                type: 'line' as const,
                label: 'Hourly Temperature',
                data: temperatures,
                borderColor: 'rgba(241, 122, 36, 0.9)',
                borderWidth: 2,
                pointRadius: 0, // Hide points
                fill: true, // Enable filling the area under the line
                tension: 0.5,
            },
            {
                type: 'bar' as const,
                label: 'Precipitation Probability',
                data: precipitation,
                borderColor: 'rgba(26, 111, 176, 1)',
                borderWidth: {
                    top: 2,
                    right: 0,
                    bottom: 0,
                    left: 0
                },
                yAxisID: 'y1',
                barPercentage: 1.0, // Ensures full width
                categoryPercentage: 1.0,  // Ensures full width
                fill: true,
            },
        ],
    };

    return (
        <div className={styles["chart-container"]} >
            <Chart type={'bar'} options={options} data={data} />
        </div >
    );
};

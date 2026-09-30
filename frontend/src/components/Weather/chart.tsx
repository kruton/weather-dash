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
import { useEffect, useRef } from 'react';
import type { PanelProfile } from '../../eink/profiles';

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

export const HourlyGraph = ({ hours, panelProfile }: { hours: HourlyForecastData[], panelProfile: PanelProfile | null }) => {
    const eink = panelProfile !== null;
    const monochrome = panelProfile === 'generic-2-color-eink';
    const chartRef = useRef<ChartJS | null>(null);

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
                        weight: eink ? 'bold' : 'normal',
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
                        weight: eink ? 'bold' : 'normal',
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
                        weight: eink ? 'bold' : 'normal',
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
                borderColor: eink ? (monochrome ? '#000000' : '#ff0000') : 'rgba(241, 122, 36, 0.9)',
                borderWidth: eink ? 3 : 2,
                backgroundColor: 'transparent',
                order: 0,
                pointRadius: 0, // Hide points
                fill: !eink, // Panel charts keep the temperature line separate from bars
                tension: 0.5,
            },
            {
                type: 'bar' as const,
                label: 'Precipitation Probability',
                data: precipitation,
                borderColor: eink ? (monochrome ? '#000000' : '#0000ff') : 'rgba(26, 111, 176, 1)',
                backgroundColor: eink ? (monochrome ? '#ffffff' : '#0000ff') : 'transparent',
                order: eink ? 1 : 0,
                borderSkipped: false,
                borderWidth: eink ? 3 : {
                    top: 2,
                    right: 0,
                    bottom: 0,
                    left: 0
                },
                yAxisID: 'y1',
                barPercentage: monochrome ? 0.65 : 1.0, // Separate outlines on monochrome panels
                categoryPercentage: 1.0,  // Ensures full width
                fill: true,
            },
        ],
    };

    useEffect(() => {
        const chart = chartRef.current;
        if (!chart || eink) return;

        const yScale = chart.scales['y'];
        const gradientStart = yScale.getPixelForValue(maxTemp);
        const gradientEnd = yScale.getPixelForValue(minTemp);

        const ctx = chart.ctx;
        const tempGradient = ctx.createLinearGradient(0, gradientStart, 0, gradientEnd + 10);
        tempGradient.addColorStop(0, 'rgba(252,204,5, 0.95)');
        tempGradient.addColorStop(1, 'rgba(252,204,5, 0.01)');
        chart.data.datasets[0].backgroundColor = tempGradient;

        const precipitationGradient = ctx.createLinearGradient(0, gradientStart, 0, gradientEnd);
        precipitationGradient.addColorStop(0, 'rgba(26, 111, 176, 0.8)');
        precipitationGradient.addColorStop(1, 'rgba(194, 223, 246, 0)');
        chart.data.datasets[1].backgroundColor = precipitationGradient;

        chart.update();
    }, [hours, maxTemp, minTemp, eink]);

    return (
        <div className={styles["chart-container"]} >
            <Chart ref={chartRef} type={'line'} options={options} data={data} />
        </div >
    );
};

import { format } from 'date-fns';

export const formatTimeString = (dt: Date, timeFormat: '12h' | '24h', includeAmPm: boolean = true): string => {
    const { time } = formatTime(dt, timeFormat, includeAmPm);
    return time;
}

/**
 * Formats a Date object based on 12h or 24h preference.
 * @param dt - The Date object to format.
 * @param timeFormat - The time format ('12h' or '24h').
 * @param includeAmPm - Whether to include AM/PM for 12h format.
 * @returns struct including time and AM/PM as unit
 */
export const formatTime = (dt: Date, timeFormat: '12h' | '24h', includeAmPm: boolean = true): { time: string, unit: string } => {
    if (timeFormat === '24h') {
        return { time: format(dt, 'HH:mm'), unit: '' };
    } else { // 12h format
        const time = format(dt, 'h:mm');
        const unit = includeAmPm ? format(dt, 'a') : '';
        return { time, unit };
    }
}

/**
 * Maps a WMO weather code to the corresponding OpenWeatherMap (OWM) icon code.
 * The mapping is based on logical interpretation as no direct official mapping exists.
 *
 * @param wmoCode - The WMO weather interpretation code.
 * @returns The base OWM icon code (e.g., '01', '10', '13').
 */
export const mapWmoToOwmIconCode = (wmoCode: number): string => {
  switch (wmoCode) {
    case 0: // Clear sky
      return '01';
    case 1: // Mainly clear
      return '02';
    case 2: // Partly cloudy
      return '03';
    case 3: // Overcast
      return '04';
    case 45: // Fog
    case 48: // Depositing rime fog
      return '50';
    case 51: // Drizzle: Light
    case 53: // Drizzle: Moderate
    case 55: // Drizzle: Dense
    case 56: // Freezing Drizzle: Light
    case 57: // Freezing Drizzle: Dense
      return '09';
    case 61: // Rain: Slight
    case 63: // Rain: Moderate
    case 65: // Rain: Heavy
    case 66: // Freezing Rain: Light
    case 67: // Freezing Rain: Heavy
      return '10';
    case 71: // Snow fall: Slight
    case 73: // Snow fall: Moderate
    case 75: // Snow fall: Heavy
    case 77: // Snow grains
      return '13';
    case 80: // Rain showers: Slight
    case 81: // Rain showers: Moderate
    case 82: // Rain showers: Violent
      return '09';
    case 85: // Snow showers slight
    case 86: // Snow showers heavy
      return '13';
    case 95: // Thunderstorm: Slight or moderate
    case 96: // Thunderstorm with slight hail
    case 99: // Thunderstorm with heavy hail
      return '11';
    default:
      // Return a sensible default, like 'clear sky', for unknown codes.
      return '01';
  }
}

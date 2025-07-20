import NewMoon from '@/assets/newmoon.png';
import FirstQuarter from '@/assets/firstquarter.png';
import LastQuarter from '@/assets/lastquarter.png';
import FullMoon from '@/assets/fullmoon.png';
import W01d from '@/assets/01d.png';
import W02d from '@/assets/02d.png';
import W03d from '@/assets/03d.png';
import W04d from '@/assets/04d.png';
import W09d from '@/assets/09d.png';
import W10d from '@/assets/10d.png';
import W11d from '@/assets/11d.png';
import W13d from '@/assets/13d.png';
import W50d from '@/assets/50d.png';
import Wind from '@/assets/wind.png';
import Humidity from '@/assets/humidity.png';
import Pressure from '@/assets/pressure.png';
import Uvi from '@/assets/uvi.png';
import Visibility from '@/assets/visibility.png';
import Aqi from '@/assets/aqi.png';
import WaningCrescent from '@/assets/waningcrescent.png';
import WaningGibbous from '@/assets/waninggibbous.png';
import WaxingCrescent from '@/assets/waxingcrescent.png';
import WaxingGibbous from '@/assets/waxinggibbous.png';
import Sunrise from '@/assets/sunrise.png';
import Sunset from '@/assets/sunset.png';


export {
  W01d, W02d, W03d, W04d, W09d, W10d, W11d, W13d, W50d,
  Wind, Humidity, Pressure, Uvi, Visibility, Aqi,
  WaningCrescent, WaningGibbous, WaxingCrescent, WaxingGibbous,
  Sunrise, Sunset,
  NewMoon, FirstQuarter, LastQuarter, FullMoon,
};

interface IconDictionary {
  [key: string]: any; // Defines keys as strings and values as numbers
}

export const WeatherIcons: IconDictionary = {
  '01': W01d,
  '02': W02d,
  '03': W03d,
  '04': W04d,
  '09': W09d,
  '10': W10d,
  '11': W11d,
  '13': W13d,
  '50': W50d,
};

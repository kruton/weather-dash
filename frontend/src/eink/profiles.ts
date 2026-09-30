// These IDs are epdoptimize palette names, not application-specific aliases.
export type PanelProfile = 'spectra6' | 'spectra6-boeber' | 'generic-2-color-eink';

export function isPanelProfile(value: string | null): value is PanelProfile {
    return value === 'spectra6' || value === 'spectra6-boeber' || value === 'generic-2-color-eink';
}

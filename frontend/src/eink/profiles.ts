// These IDs are epdoptimize palette names, not application-specific aliases.
export type PanelProfile = 'spectra6' | 'spectra6-boeber' | 'acep' | 'generic-2-color-eink' | 'generic-4-grayscale';

export function isPanelProfile(value: string | null): value is PanelProfile {
    return value === 'spectra6' || value === 'spectra6-boeber' || value === 'acep' || value === 'generic-2-color-eink' || value === 'generic-4-grayscale';
}

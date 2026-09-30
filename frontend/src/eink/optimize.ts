import {
    ditherImage,
    replaceColors,
    spectra6Palette,
    spectra6BoeberPalette,
    genericTwoColorEinkPalette,
    suggestCanvasProcessingOptions,
} from 'epdoptimize';
import type { DitherImageOptions } from 'epdoptimize';
import type { PanelProfile } from './profiles';
import { isPanelProfile } from './profiles';

const palettes: Record<PanelProfile, typeof spectra6Palette> = {
    spectra6: spectra6Palette,
    'spectra6-boeber': spectra6BoeberPalette,
    'generic-2-color-eink': genericTwoColorEinkPalette,
};

export interface OptimizeRequest {
    pngBase64: string;
    panelProfile: PanelProfile;
}

export interface OptimizeResult {
    pngBase64: string;
    deviceColors: string[];
}

function readableOptions(source: HTMLCanvasElement, palette: typeof spectra6Palette): DitherImageOptions {
    const suggestion = suggestCanvasProcessingOptions(source, palette, { intent: 'readable' });
    const range = suggestion.ditherOptions.dynamicRangeCompression;
    return {
        ...suggestion.ditherOptions,
        palette,
        ditheringType: 'errorDiffusion',
        errorDiffusionMatrix: 'floydSteinberg',
        serpentine: true,
        colorMatching: 'lab',
        processingEngine: 'js',
        edgePreservation: { enabled: true, strength: 1, radius: 1 },
        edgeAntialiasing: { enabled: true, strength: 1 },
        dynamicRangeCompression: {
            ...(typeof range === 'object' ? range : {}),
            mode: 'display',
            preserveWhite: true,
        },
    };
}

async function processPalette(source: HTMLCanvasElement, palette: typeof spectra6Palette): Promise<HTMLCanvasElement> {
    const calibrated = document.createElement('canvas');
    await ditherImage(source, calibrated, readableOptions(source, palette));
    const device = document.createElement('canvas');
    replaceColors(calibrated, device, palette);
    return device;
}

export async function optimizeScreenshot({ pngBase64, panelProfile }: OptimizeRequest): Promise<OptimizeResult> {
    if (!isPanelProfile(panelProfile)) throw new Error('Unknown panel profile');
    const palette = palettes[panelProfile];
    const bytes = Uint8Array.from(atob(pngBase64), character => character.charCodeAt(0));
    const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
    const source = document.createElement('canvas');
    source.width = bitmap.width;
    source.height = bitmap.height;
    const context = source.getContext('2d');
    if (!context) throw new Error('Canvas 2D context unavailable');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, source.width, source.height);
    context.drawImage(bitmap, 0, 0);
    bitmap.close();

    const device = await processPalette(source, palette);
    if (panelProfile !== 'generic-2-color-eink') {
        // Calibrated color inks can be nearer to mid-gray than black/white.
        // Keep neutral UI/text free of colored speckles, using the library's
        // monochrome processing rather than a separate dithering algorithm.
        const monochrome = await processPalette(source, genericTwoColorEinkPalette);
        const deviceContext = device.getContext('2d');
        const monoContext = monochrome.getContext('2d');
        if (!deviceContext || !monoContext) throw new Error('Canvas 2D context unavailable');
        const original = context.getImageData(0, 0, source.width, source.height).data;
        const output = deviceContext.getImageData(0, 0, source.width, source.height);
        const neutral = monoContext.getImageData(0, 0, source.width, source.height).data;
        for (let pixel = 0; pixel < original.length; pixel += 4) {
            const r = original[pixel], g = original[pixel + 1], b = original[pixel + 2];
            if (Math.max(r, g, b) - Math.min(r, g, b) <= 16) {
                output.data[pixel] = neutral[pixel];
                output.data[pixel + 1] = neutral[pixel + 1];
                output.data[pixel + 2] = neutral[pixel + 2];
            }
        }
        deviceContext.putImageData(output, 0, 0);
    }
    return {
        pngBase64: device.toDataURL('image/png').split(',')[1],
        deviceColors: palette.map(entry => entry.deviceColor),
    };
}

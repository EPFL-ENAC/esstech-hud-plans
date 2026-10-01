const storageKey = 'hud-language';

export type AppLocale = 'en' | 'fr' | 'es';

export function detectBrowserLocale(): AppLocale {
    const browserLocales = [...(navigator.languages ?? []), navigator.language];
    for (const browserLocale of browserLocales) {
        const candidate = browserLocale?.split('-')[0]?.toLowerCase();
        if (candidate === 'en' || candidate === 'fr' || candidate === 'es') {
            return candidate;
        }
    }
    return 'en';
}

export function loadSavedLocale(): AppLocale | null {
    try {
        const locale = localStorage.getItem(storageKey);
        if (locale === 'en' || locale === 'fr' || locale === 'es') {
            return locale;
        }
    } catch {
        // Language switching still works when browser storage is unavailable.
    }
    return null;
}

export function saveLocale(locale: AppLocale): void {
    try {
        localStorage.setItem(storageKey, locale);
    } catch {
        // Keep the selected language for this session if it cannot be saved.
    }
}

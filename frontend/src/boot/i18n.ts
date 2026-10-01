import { defineBoot } from '#q-app/wrappers';
import { Lang } from 'quasar';
import enUS from 'quasar/lang/en-US';
import fr from 'quasar/lang/fr';
import es from 'quasar/lang/es';
import { watch } from 'vue';
import { i18n, type MessageSchema } from 'src/i18n/instance';
import { detectBrowserLocale, loadSavedLocale } from 'src/lib/language';

export type { MessageLanguages, MessageSchema } from 'src/i18n/instance';

// See https://vue-i18n.intlify.dev/guide/advanced/typescript.html#global-resource-schema-type-definition
/* eslint-disable @typescript-eslint/no-empty-object-type */
declare module 'vue-i18n' {
    // define the locale messages schema
    export interface DefineLocaleMessage extends MessageSchema {}

    // define the datetime format schema
    export interface DefineDateTimeFormat {}

    // define the number format schema
    export interface DefineNumberFormat {}
}
/* eslint-enable @typescript-eslint/no-empty-object-type */

export default defineBoot(({ app }) => {
    app.use(i18n);

    const quasarLanguages = { en: enUS, fr, es };

    i18n.global.locale.value = loadSavedLocale() ?? detectBrowserLocale();

    watch(
        i18n.global.locale,
        (locale) => {
            Lang.set(quasarLanguages[locale]);
            document.documentElement.lang = locale;
        },
        { immediate: true },
    );
});

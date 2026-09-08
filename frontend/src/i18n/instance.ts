import { createI18n } from 'vue-i18n';
import messages from 'src/i18n';

export type MessageLanguages = keyof typeof messages;
export type MessageSchema = (typeof messages)['en-US'];

// Shared by the Quasar boot module and helpers outside component setup.
export const i18n = createI18n<{ message: MessageSchema }, MessageLanguages, false>({
    legacy: false,
    locale: 'en-US',
    fallbackLocale: 'en-US',
    messages,
});

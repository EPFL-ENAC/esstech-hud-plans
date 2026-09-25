import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';
import { createPinia, disposePinia, setActivePinia } from 'pinia';

const { outputText } = ts.transpileModule(
    readFileSync(new URL('../src/stores/pwaInstall.ts', import.meta.url), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } },
);
const source = outputText
    .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
    .replace("from 'pinia'", `from '${import.meta.resolve('pinia')}'`);
const { usePwaInstallStore } = await import(
    `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
);

function browser(t, { standalone = false, iosStandalone = false } = {}) {
    const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
    const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
    const displayMode = Object.assign(new EventTarget(), { matches: standalone });
    const window = Object.assign(new EventTarget(), { matchMedia: () => displayMode });
    Object.defineProperty(globalThis, 'window', { configurable: true, value: window });
    Object.defineProperty(globalThis, 'navigator', {
        configurable: true,
        value: { standalone: iosStandalone },
    });
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = usePwaInstallStore();
    store.startTracking();
    const stop = () => store.stopTracking();
    t.after(() => {
        disposePinia(pinia);
        setActivePinia(undefined);
        if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
        else delete globalThis.window;
        if (originalNavigator) Object.defineProperty(globalThis, 'navigator', originalNavigator);
        else delete globalThis.navigator;
    });
    return { window, displayMode, stop };
}

function installEvent(prompt = async () => {}, outcome = 'accepted') {
    return Object.assign(new Event('beforeinstallprompt', { cancelable: true }), {
        prompt,
        userChoice: Promise.resolve({ outcome }),
    });
}

test('captures the install event at boot and shares it across page consumers', async (t) => {
    const { window } = browser(t);
    let calls = 0;
    const event = installEvent(async () => {
        calls++;
    });
    window.dispatchEvent(event);
    assert.equal(event.defaultPrevented, true);
    const login = usePwaInstallStore();
    const more = usePwaInstallStore();
    assert.equal(more.canPrompt, true);
    assert.deepEqual(await Promise.all([login.promptInstall(), more.promptInstall()]), [
        'accepted',
        'unavailable',
    ]);
    assert.equal(calls, 1);
    assert.equal(login.canPrompt, false);
});

test('dismissal consumes the prompt; a later browser event enables a new attempt', async (t) => {
    const { window } = browser(t);
    const install = usePwaInstallStore();
    window.dispatchEvent(installEvent(undefined, 'dismissed'));
    assert.equal(await install.promptInstall(), 'dismissed');
    assert.equal(await install.promptInstall(), 'unavailable');
    window.dispatchEvent(installEvent());
    assert.equal(await install.promptInstall(), 'accepted');
});

test('unsupported or failed prompts permit manual installation guidance', async (t) => {
    const { window } = browser(t);
    const install = usePwaInstallStore();
    assert.equal(await install.promptInstall(), 'unavailable');
    window.dispatchEvent(
        installEvent(async () => {
            throw new Error('Not allowed');
        }),
    );
    assert.equal(await install.promptInstall(), 'unavailable');
    assert.equal(install.canPrompt, false);
});

test('standalone display changes and iOS standalone suppress prompting', async (t) => {
    const { window, displayMode } = browser(t, { iosStandalone: true });
    const install = usePwaInstallStore();
    window.dispatchEvent(installEvent());
    assert.equal(install.standalone, true);
    assert.equal(await install.promptInstall(), 'unavailable');
    navigator.standalone = false;
    window.dispatchEvent(new Event('pageshow'));
    assert.equal(install.standalone, false);
    displayMode.matches = true;
    displayMode.dispatchEvent(new Event('change'));
    assert.equal(install.standalone, true);
});

test('installation and cleanup discard stale prompts without reloading', (t) => {
    const { window, stop } = browser(t);
    const install = usePwaInstallStore();
    window.dispatchEvent(installEvent());
    window.dispatchEvent(new Event('appinstalled'));
    assert.equal(install.canPrompt, false);
    stop();
    const event = installEvent();
    window.dispatchEvent(event);
    assert.equal(event.defaultPrevented, false);
    assert.equal(install.canPrompt, false);
});

test('store disposal removes listeners even after repeated tracking starts', (t) => {
    const { window } = browser(t);
    const store = usePwaInstallStore();
    store.startTracking();
    store.$dispose();
    const event = installEvent();
    window.dispatchEvent(event);
    assert.equal(event.defaultPrevented, false);
    assert.equal(store.canPrompt, false);
});

test('separate Pinia instances do not share installation state', (t) => {
    const { window } = browser(t);
    const first = usePwaInstallStore();
    const otherPinia = createPinia();
    const second = usePwaInstallStore(otherPinia);
    t.after(() => disposePinia(otherPinia));
    window.dispatchEvent(installEvent());
    assert.equal(first.canPrompt, true);
    assert.equal(second.canPrompt, false);
    assert.notEqual(first, second);
});

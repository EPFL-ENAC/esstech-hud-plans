import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setImmediate as nextTurn } from 'node:timers/promises';
import { test } from 'node:test';
import { compileScript, parse } from '@vue/compiler-sfc';
import { createRenderer, h, ref } from 'vue';
import { deferred, importTypeScriptSource } from './helpers/typescript.mjs';

function element(type, text = '') {
    return { type, text, props: {}, children: [], parent: null };
}

function remove(node) {
    if (!node.parent) return;
    const siblings = node.parent.children;
    siblings.splice(siblings.indexOf(node), 1);
    node.parent = null;
}

const renderer = createRenderer({
    createElement: element,
    createText: (text) => element('text', text),
    createComment: () => element('comment'),
    insert(node, parent, anchor = null) {
        remove(node);
        const index = anchor ? parent.children.indexOf(anchor) : parent.children.length;
        parent.children.splice(index, 0, node);
        node.parent = parent;
    },
    remove,
    setText: (node, text) => (node.text = text),
    setElementText(node, text) {
        node.text = text;
        node.children = [];
    },
    parentNode: (node) => node.parent,
    nextSibling: (node) => {
        const siblings = node.parent?.children ?? [];
        return siblings[siblings.indexOf(node) + 1] ?? null;
    },
    patchProp: (node, key, previous, value) => (node.props[key] = value),
});

function descendants(node) {
    return [node, ...node.children.flatMap(descendants)];
}

const slotContainer = (_, { attrs, slots }) =>
    h('div', attrs, [slots.default?.(), slots.action?.()]);

async function fixture(t, path) {
    const imports = [];
    const downloads = [];
    const buffer = new ArrayBuffer(16);
    const splat = { buffer, viewParams: { matrix: [], radius: 2 } };
    let events;
    const scene = {
        props: ['splatData'],
        emits: ['ready', 'error'],
        setup(props, { emit }) {
            assert.equal(props.splatData, buffer);
            events = {
                ready: () => emit('ready'),
                error: () => emit('error', new Error('renderer failed')),
            };
            return () => h('canvas');
        },
    };
    // Substitute only external boundaries; compile the real setup and template.
    const source = readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')
        .replace(
            '<script setup lang="ts">',
            '<script setup lang="ts">\nimport { loadRenderer } from \'splat-test-boundaries\';',
        )
        .replace(
            /import (\w+) from 'src\/components\/[^']+';/g,
            "import { $1 } from 'splat-test-boundaries';",
        )
        .replace("import('src/components/SplatRenderer.vue')", 'loadRenderer()');
    const { descriptor } = parse(source);
    const { content } = compileScript(descriptor, { id: path, inlineTemplate: true });
    const { default: component } = await importTypeScriptSource(t, content, {
        vue: import.meta.resolve('vue'),
        'vue-router': {
            useRoute: () => ({
                params: { buildingId: 'building', reconstructionId: 'reconstruction' },
            }),
        },
        'vue-i18n': { useI18n: () => ({ t: (key) => key }) },
        'src/lib/buildings': {
            ApiError: class ApiError extends Error {},
            getReconstructionSplat(...args) {
                downloads.push(args);
                return Promise.resolve(buffer);
            },
        },
        'src/queries/reconstructions': {
            useReconstructionSplatQuery: () => ({
                data: ref(splat),
                error: ref(null),
                state: ref({ status: 'success', data: splat }),
                asyncStatus: ref('idle'),
                refetch: () => assert.fail('Rendering retry must reuse the downloaded splat'),
            }),
        },
        'splat-test-boundaries': {
            loadRenderer() {
                const gate = deferred();
                imports.push(gate);
                return gate.promise;
            },
            PageHeader: () => null,
            SplatDownloadProgress: () => null,
            QueryStateSwitcher: (props, { slots }) => slots.success({ data: props.state.data }),
        },
    });
    const app = renderer.createApp(component, {
        buildingId: 'building',
        reconstructionId: 'reconstruction',
    });
    for (const tag of ['q-page', 'q-card', 'q-banner', 'q-spinner']) {
        app.component(tag, slotContainer);
    }
    app.component('q-btn', (_, { attrs }) => h('button', attrs, attrs.label));
    app.config.errorHandler = () => {};
    const root = element('root');
    app.mount(root);
    t.after(() => app.unmount());
    function button(label) {
        return descendants(root).find((node) => node.type === 'button' && node.text === label);
    }
    if (button('Load splat')) await button('Load splat').props.onClick();
    await nextTurn();
    return {
        imports,
        downloads,
        events: () => events,
        retry: async () => {
            const action = button('Retry') ?? button('common.retry');
            assert.ok(action, 'Retry action is visible');
            await action.props.onClick();
            await nextTurn();
        },
        preparing: () =>
            descendants(root).some((node) =>
                /Preparing splat|plans.splat.preparing/.test(node.text),
            ),
        alerts: () => descendants(root).filter((node) => node.props.role === 'alert'),
        scene,
    };
}

for (const path of ['src/pages/ReconstructionPlanPage.vue']) {
    test(`${path}: rejected imports remain retryable and recover`, async (t) => {
        const f = await fixture(t, path);
        for (let attempt = 0; attempt < 2; attempt++) {
            assert.equal(f.preparing(), true);
            assert.equal(f.imports.length, attempt + 1);
            f.imports[attempt].reject(new Error('chunk failed'));
            await nextTurn();
            assert.equal(f.preparing(), false);
            assert.equal(f.alerts().length, 1);
            await f.retry();
            assert.equal(f.alerts().length, 0);
        }
        assert.equal(f.imports.length, 3);
        f.imports[2].resolve(f.scene);
        await nextTurn();
        f.events().ready();
        await nextTurn();
        assert.equal(f.preparing(), false);
        assert.equal(f.alerts().length, 0);
        assert.equal(f.downloads.length, 0);
    });

    test(`${path}: successful imports preserve ready and renderer error handling`, async (t) => {
        const f = await fixture(t, path);
        f.imports[0].resolve(f.scene);
        await nextTurn();
        assert.equal(f.preparing(), true);
        f.events().ready();
        await nextTurn();
        assert.equal(f.preparing(), false);
        assert.equal(f.alerts().length, 0);
        f.events().error();
        await nextTurn();
        assert.equal(f.alerts().length, 1);
        await f.retry();
        assert.equal(f.imports.length, 1, 'Successfully loaded renderer module is reused');
        f.events().ready();
        await nextTurn();
        assert.equal(f.preparing(), false);
        assert.equal(f.alerts().length, 0);
    });
}

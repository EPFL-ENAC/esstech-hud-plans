import { readFileSync } from 'node:fs';
import ts from 'typescript';

const dependencies = new Map();
const registry = Symbol.for('hud.tests.typescriptDependencies');
globalThis[registry] = dependencies;
let moduleId = 0;

export function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((done, fail) => {
        resolve = done;
        reject = fail;
    });
    return { promise, resolve, reject };
}

/** Import the real TypeScript implementation with isolated test boundaries. */
export async function importTypeScriptSource(t, source, imports) {
    const { outputText } = ts.transpileModule(source, {
        compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    });
    const code = outputText.replace(/from (['"])([^'"]+)\1/g, (statement, quote, name) => {
        if (!(name in imports)) return statement;
        let url = imports[name];
        if (typeof url !== 'string') {
            const id = ++moduleId;
            dependencies.set(id, url);
            t.after(() => dependencies.delete(id));
            const exports = Object.keys(url)
                .map((key) => `export const ${key} = dependency.${key};`)
                .join('\n');
            url = `data:text/javascript;base64,${Buffer.from(
                `const dependency = globalThis[Symbol.for('hud.tests.typescriptDependencies')].get(${id});\n${exports}`,
            ).toString('base64')}`;
        }
        return `from '${url}'`;
    });
    return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}

export function importTypeScript(t, path, imports) {
    const source = readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');
    return importTypeScriptSource(t, source, imports);
}

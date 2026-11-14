import assert from 'node:assert/strict';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// node tests/network-dependent-tasks.browser.mjs /path/to/playwright/index.mjs [dev-url]
const { chromium } = await import(
    process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright'
);
const origin = process.argv[3] ?? 'http://localhost:9000';
const token = `test.${Buffer.from(
    JSON.stringify({ sub: 'task-owner', exp: 4_000_000_000 }),
).toString('base64url')}.test`;

const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
    for (const viewport of [
        { width: 390, height: 844 },
        { width: 1280, height: 900 },
    ]) {
        const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
        const page = await context.newPage();
        const errors = [];
        page.setDefaultTimeout(10_000);
        page.on('pageerror', (error) => errors.push(error.message));
        try {
            await context.addInitScript((accessToken) => {
                localStorage.setItem('access_token', accessToken);
                localStorage.setItem('hud-language', 'en');
            }, token);
            await context.route('**/env.js', (route) =>
                route.fulfill({
                    contentType: 'application/javascript',
                    body: `window.env=${JSON.stringify({
                        API_URL: origin,
                        API_PATH: '/network-task-api',
                        KEYCLOAK_ENDPOINT: origin,
                        KEYCLOAK_REALM: 'test',
                        KEYCLOAK_CLIENT_ID: 'test',
                        SENTRY_RATE: '0',
                    })};`,
                }),
            );
            await context.route('**/network-task-api/**', (route) => {
                const path = new URL(route.request().url()).pathname;
                return route.fulfill({
                    json: path.endsWith('/user/me')
                        ? {
                              id: 'task-owner',
                              name: 'Task owner',
                              username: 'task-owner',
                              email: 'owner@example.test',
                              terms_accepted: true,
                          }
                        : { items: [], total: 0 },
                });
            });

            await page.goto(`${origin}/#/more`);
            await page.locator('a[href="#/more/tasks"]').click();
            const taskPage = page.getByRole('main', { name: 'Pending tasks' });
            await taskPage.getByText('No pending tasks.', { exact: true }).waitFor();

            // Inject test-only tasks; no production demo task or control is needed.
            await page.evaluate(async () => {
                const { NetworkDependentTask } = await import('/src/lib/networkDependentTasks.ts');
                const { useNetworkDependentTasks } =
                    await import('/src/stores/networkDependentTasks.ts');
                const queue = useNetworkDependentTasks();
                const submitted = new Map();
                class BrowserTask extends NetworkDependentTask {
                    constructor(label, failOnce) {
                        super({ ownerId: 'task-owner', label });
                        this.failOnce = failOnce;
                        this.finish = null;
                    }
                    resume(signal) {
                        if (this.failOnce) {
                            this.failOnce = false;
                            return Promise.reject(new Error('Connection interrupted'));
                        }
                        return new Promise((resolve, reject) => {
                            this.finish = resolve;
                            signal.addEventListener('abort', () => reject(signal.reason), {
                                once: true,
                            });
                        });
                    }
                    failureAction() {
                        return 'retry';
                    }
                    report(completed, total) {
                        this.mutableState.progress = { completed, total };
                    }
                }
                window.taskHarness = {
                    queue,
                    submitted,
                    submit(label, failOnce = false) {
                        const task = new BrowserTask(label, failOnce);
                        submitted.set(label, task);
                        queue.submit(task);
                    },
                };
            });

            await page.getByRole('button', { name: 'Back', exact: true }).click();
            await context.setOffline(true);
            await page.waitForFunction(() => window.taskHarness.queue.isOnline === false);
            await page.evaluate(() => {
                window.taskHarness.submit('First task');
                window.taskHarness.submit('Second task');
            });
            const moreLink = page.locator('a[href="#/more/tasks"]');
            await moreLink.locator('.q-badge').getByText('2').waitFor();
            await moreLink.click();
            assert.equal(await taskPage.getByText('Queued', { exact: true }).count(), 2);

            await context.setOffline(false);
            await page.waitForFunction(() => {
                const { submitted } = window.taskHarness;
                return ['First task', 'Second task'].every(
                    (label) => submitted.get(label).state.status === 'running',
                );
            });
            await taskPage.getByText('Running', { exact: true }).first().waitFor();
            assert.equal(await taskPage.getByText('Running', { exact: true }).count(), 2);
            await page.evaluate(() => window.taskHarness.submitted.get('First task').report(2, 4));
            await taskPage.getByText('2 / 4', { exact: true }).waitFor();

            await taskPage.getByRole('button', { name: 'Cancel First task' }).click();
            await taskPage.getByText('First task', { exact: true }).waitFor({ state: 'detached' });
            await taskPage.getByText('Running', { exact: true }).waitFor();
            await page.evaluate(() => window.taskHarness.submitted.get('Second task').finish());
            await taskPage.getByText('No pending tasks.', { exact: true }).waitFor();

            await page.evaluate(() => window.taskHarness.submit('Retried task', true));
            await taskPage.getByText('Waiting for connection', { exact: true }).waitFor();
            await page.evaluate(() => window.dispatchEvent(new Event('online')));
            assert.equal(
                await page.evaluate(
                    () => window.taskHarness.submitted.get('Retried task').state.attempts,
                ),
                1,
            );
            await context.setOffline(true);
            await page.waitForFunction(() => window.taskHarness.queue.isOnline === false);
            assert.equal(
                await taskPage.getByRole('button', { name: 'Retry Retried task' }).isDisabled(),
                true,
            );
            await context.setOffline(false);
            await taskPage.getByText('Running', { exact: true }).waitFor();
            await taskPage.getByRole('button', { name: 'Cancel Retried task' }).click();
            await taskPage.getByText('No pending tasks.', { exact: true }).waitFor();

            await page.evaluate(() => window.taskHarness.submit('Manual task', true));
            await taskPage.getByText('Waiting for connection', { exact: true }).waitFor();
            await taskPage.getByRole('button', { name: 'Retry Manual task' }).click();
            await taskPage.getByText('Running', { exact: true }).waitFor();
            await page.evaluate(() => {
                const task = window.taskHarness.submitted.get('Manual task');
                task.onInterrupt = () =>
                    new Promise((resolve) => {
                        task.finishCancellation = resolve;
                    });
            });
            await taskPage.getByRole('button', { name: 'Cancel Manual task' }).click();
            await taskPage.getByText('Cancelling', { exact: true }).waitFor();
            assert.equal(
                await taskPage.getByRole('button', { name: 'Cancel Manual task' }).isDisabled(),
                true,
            );
            await page.evaluate(() =>
                window.taskHarness.submitted.get('Manual task').finishCancellation(),
            );
            await taskPage.getByText('No pending tasks.', { exact: true }).waitFor();

            // Locale changes update the task page and More menu.
            await page.getByRole('button', { name: 'Back', exact: true }).click();
            await page.locator('a[href="#/more/settings"]').click();
            await page.getByRole('combobox', { name: 'Language', exact: true }).click();
            await page.getByRole('option', { name: 'Français', exact: true }).click();
            await page.getByRole('button', { name: 'Retour', exact: true }).click();
            await page.locator('a[href="#/more/tasks"]').click();
            await page.getByText('Aucune tâche en attente.', { exact: true }).waitFor();
            await page.getByRole('button', { name: 'Retour', exact: true }).click();
            await page.locator('a[href="#/more/settings"]').click();
            await page.getByRole('combobox', { name: 'Langue', exact: true }).click();
            await page.getByRole('option', { name: 'Español', exact: true }).click();
            await page.getByRole('button', { name: 'Volver', exact: true }).click();
            await page.locator('a[href="#/more/tasks"]').click();
            await page.getByText('No hay tareas pendientes.', { exact: true }).waitFor();
            assert.deepEqual(errors, []);
            console.log(`Pending tasks: passed at ${viewport.width}x${viewport.height}`);
        } catch (error) {
            console.error({
                viewport,
                url: page.url(),
                errors,
                body: await page.locator('body').innerText(),
            });
            await page.screenshot({
                path: join(tmpdir(), `hud-network-tasks-${viewport.width}-failure.png`),
            });
            throw error;
        } finally {
            await context.close();
        }
    }
} finally {
    await browser.close();
}

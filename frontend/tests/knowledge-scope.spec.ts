import { test, expect } from "@playwright/test";
const headers = { "X-ESA-Request": "1" };

for (const stranded of [false, true])
  test(`missing scope recovery ${stranded ? 'already selected' : 'first selection'} preserves draft and business facts`, async ({ page, request }, info) => {
    const kb = await (await request.post('/api/library', {headers, data: {name: '补选恢复合成库'}})).json();
    const task = await (await request.post('/api/tasks', {headers, data: {request: {kind: 'loan', execution_ceiling: 'PREVIEW_ONLY', confirmed: true}}})).json();
    await request.post('/__test/decisions/' + task.task_id, {data: [
      [['update_parameters', {changes: {}, turn_request: {preview: false, knowledge_quote: '补选资料范围测试'}}]],
      [['finish', {}]],
    ]});
    await page.goto('/#/assistant?c=' + task.conversation_id);
    await page.getByRole('checkbox', {name: /深入/}).check();
    const input = page.getByRole('textbox', {name: '给助理发消息'});
    await input.fill('只解释补选资料范围测试，不准备申请。');
    await page.getByRole('button', {name: '发送', exact: true}).click();
    await expect(page.getByRole('button', {name: '选择资料库后继续解释', exact: true})).toBeVisible();
    await expect(page.getByRole('button', {name: '重试解释', exact: true})).toHaveCount(0);
    await page.getByRole('button', {name: '选择资料库后继续解释', exact: true}).click();
    await expect(page.getByRole('combobox', {name: '当前资料库'})).toBeFocused();
    await page.locator('.task-summary').click();
    await page.getByRole('dialog').getByRole('link', {name: '选择资料库后继续解释'}).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    if (stranded) {
      await request.post(`/__test/legacy-scope/${task.conversation_id}/${kb.id}`);
      await page.reload();
      await expect(page.getByRole('combobox', {name: '当前资料库'})).toHaveValue(kb.id);
    }
    await input.fill('未发送的新草稿 保留中文');
    if (!stranded) {
      await page.getByRole('combobox', {name: '当前资料库'}).selectOption(kb.id);
      await expect(page.getByText('资料库已选择，可继续刚才的问题。')).toBeVisible();
    }
    await expect(input).toHaveValue('未发送的新草稿 保留中文');
    const before = await (await request.get('/api/tasks/' + task.task_id)).json();
    const calls: {method: string, url: string}[] = [];
    page.on('request', r => calls.push({method: r.method(), url: r.url()}));
    await page.getByRole('button', {name: '重试解释', exact: true}).click();
    await expect(page.getByText('UI外部回答替身，非实时模型。', {exact: true})).toBeVisible();
    await expect(input).toHaveValue('未发送的新草稿 保留中文');
    expect(calls.some(r => r.method === 'PATCH' && r.url.endsWith('/api/conversations/' + task.conversation_id))).toBeTruthy();
    const after = await (await request.get('/api/tasks/' + task.task_id)).json();
    expect(after.facts).toEqual(before.facts);
    expect(after.facts_revision).toBe(before.facts_revision);
    expect(after.preview).toBeNull();
    expect(after.receipt).toBeFalsy();
    const runs = await (await request.get(`/api/product/conversations/${task.conversation_id}/runs`)).json();
    expect(JSON.parse(runs[0].input_json).detailed).toBe(true);
    await page.setViewportSize({width: 390, height: 844});
    await expect(input).toHaveCount(1);
    await input.dispatchEvent('compositionstart');
    await input.press('Enter');
    await input.dispatchEvent('compositionend');
    await expect(input).toHaveValue('未发送的新草稿 保留中文\n');
    const conversation = await (await request.get('/api/conversations/' + task.conversation_id)).json();
    expect(conversation.turns.filter((t: {role: string}) => t.role === 'user')).toHaveLength(1);
    await expect(page.getByRole('button', {name: '发送', exact: true})).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({path: info.outputPath('scope-recovery-mobile.png'), fullPage: true});
  });

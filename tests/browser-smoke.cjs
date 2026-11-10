const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, "../docs");
const mime = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".json": "application/json",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};
const server = http.createServer((req, res) => {
  const name = path.resolve(
    root,
    "." + decodeURIComponent(new URL(req.url, "http://local").pathname),
  );
  if (name !== root && !name.startsWith(root + path.sep)) {
    res.writeHead(403).end();
    return;
  }
  const file =
    fs.existsSync(name) && fs.statSync(name).isDirectory()
      ? path.join(name, "index.html")
      : name;
  fs.readFile(file, (err, body) => {
    if (err) {
      res.writeHead(404).end();
      return;
    }
    res.setHeader(
      "Content-Type",
      mime[path.extname(file)] || "application/octet-stream",
    );
    res.end(body);
  });
});
(async () => {
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const system = process.env.CHROMIUM_PATH || "/usr/bin/chromium";
  const browser = await chromium.launch({
    headless: true,
    ...(fs.existsSync(system) ? { executablePath: system } : {}),
    args: ["--no-sandbox"],
  });
  try {
    const skipped = [];
    // Reproduce previews where the separate JSON asset returns HTTP 404.
    const preview = await browser.newPage({viewport: {width: 1512, height: 1100}});
    let dataRequests = 0;
    await preview.route("**/data/map.json", route => {
      dataRequests++;
      return route.fulfill({status: 404, body: "Not found"});
    });
    await preview.goto(base);
    await preview.waitForSelector("#papers .paper-card");
    assert.equal(await preview.locator("#papers .paper-card").count(), 45);
    assert.equal(await preview.evaluate(() => network.body.nodeIndices.length), 9);
    assert.equal(dataRequests, 0, "Embedded data avoids the missing JSON route");
    await preview.screenshot({path: "/tmp/affective-atlas-loading-fixed.png", fullPage: true});
    await preview.close();

    // Directly opening the generated HTML must also show the map without fetch.
    const localFile = await browser.newPage();
    try {
      await localFile.goto(pathToFileURL(path.join(root, "index.html")).href);
      await localFile.waitForSelector("#papers .paper-card");
      assert.equal(await localFile.locator("#papers .paper-card").count(), 45);
      assert.equal(await localFile.evaluate(() => network.body.nodeIndices.length), 9);
    } catch (e) {
      if (!e.message.includes("ERR_BLOCKED_BY_ADMINISTRATOR")) throw e;
      skipped.push("Direct file:// navigation is blocked by managed browser policy");
    } finally {
      await localFile.close();
    }

    const page = await browser.newPage({
      viewport: { width: 1512, height: 1100 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    await page.waitForSelector("#papers .paper-card");
    assert.equal(await page.locator("#papers .paper-card").count(), 45);
    assert.equal(
      await page.evaluate(() => network.body.nodeIndices.length),
      9,
      "Overview shows readable top-level domains",
    );
    for (const topic of [
      "emotion",
      "support",
      "social",
      "alignment",
      "personalization",
      "psychology",
      "hai",
      "evaluation",
    ]) {
      await page.locator("#topic").selectOption(topic);
      assert.ok((await page.locator("#papers .paper-card").count()) > 0, topic);
    }
    await page.locator("#reset").click();
    await page.locator("#query").fill("FANToM");
    assert.equal(await page.locator("#papers .paper-card").count(), 1);
    await page.locator("#papers .paper-card").click();
    assert.match(await page.locator("#details h2").innerText(), /FANToM/);
    assert.equal(
      await page.locator("#details a").first().getAttribute("href"),
      "https://aclanthology.org/2023.emnlp-main.890/",
    );
    // Exercise the real canvas hover event and its tooltip content.
    await page.locator("#graph").scrollIntoViewIfNeeded();
    await page.evaluate(() => {
      network.fit();
      network.selectNodes([]);
    });
    const id = "paper:2023.emnlp-main.890";
    const point = await page.evaluate(
      (id) => network.canvasToDOM(network.getPositions([id])[id]),
      id,
    );
    const bounds = await page.locator("#graph").boundingBox();
    await page.mouse.move(bounds.x + point.x, bounds.y + point.y);
    await page.waitForSelector(".vis-tooltip", { state: "visible" });
    assert.match(await page.locator(".vis-tooltip").innerText(), /2023/);
    await page.locator("#view").selectOption("citations");
    assert.match(await page.locator("#graph-status").innerText(), /관계 0개/);
    await page.locator("#query").fill("<img src=x onerror=alert(1)>");
    assert.match(
      await page.locator("#papers").innerText(),
      /조건에 맞는 논문이 없습니다/,
    );
    await page.locator("#reset").click();
    await page.locator("#view").selectOption("topics");
    await page.screenshot({
      path: "/tmp/affective-atlas-desktop.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await page.screenshot({
      path: "/tmp/affective-atlas-mobile.png",
      fullPage: true,
    });
    await page.goto(base + "/review.html");
    assert.match(await page.title(), /문헌 검토/);
    assert.ok((await page.locator("article section").count()) >= 45);
    // Import through the upstream program's actual file input, without an API.
    await page.goto(base + "/tools/local-citation-network/");
    await page
      .locator("input[type=file]")
      .first()
      .setInputFiles(path.join(root, "data/local-citation-network.json"));
    await page.waitForFunction(
      () => typeof vm !== "undefined" && vm.seedArticles.length === 45,
    );
    assert.equal(await page.evaluate(() => vm.seedArticles.length), 45);
    assert.equal(
      await page.evaluate(() => vm.currentGraph.localCitationNetworkVersion),
      1.32,
    );
    assert.equal(
      await page.evaluate(() => vm.currentGraph.citedArticles.length),
      0,
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS browser: missing JSON route; 8 domains; search; paper detail and URL; canvas hover; empty citation state; no-result search; mobile layout; review page; upstream native import (45 papers); no page errors.",
    );
    for (const reason of skipped) console.log("SKIP: " + reason);
    if (!skipped.length) console.log("PASS browser: direct HTML file");
  } finally {
    await browser.close();
  }
})()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => server.close());

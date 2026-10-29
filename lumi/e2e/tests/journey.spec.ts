import { expect, test, type BrowserContext, type Page } from "@playwright/test";

// One user, one browser, one run: register, add a profile, connect Facebook and PFM, chat, read
// the status back, then sign out. Providers are simulated by e2e/sim.py; the consent screens are
// answered here by redirecting the provider URL to the frontend callback page, as the real providers do.

const FRONT = "http://localhost:3010";
const EMAIL = `e2e-${Date.now()}@example.com`;
const PASSWORD = "Passw0rd-e2e-long";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let denyNextConsent = false;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext();
  // Facebook consent: the user "accepts" and the provider sends the browser back with a code.
  await context.route("https://www.facebook.com/**", async (route) => {
    const state = new URL(route.request().url()).searchParams.get("state") ?? "";
    const outcome = denyNextConsent ? "error=access_denied" : "code=SIM-CODE";
    denyNextConsent = false;
    await route.fulfill({
      status: 302,
      headers: { location: `${FRONT}/connections/meta/callback?${outcome}&state=${state}` },
    });
  });
  // PFM consent: a simulated page flips the account on and redirects to the frontend PFM page.
  await context.route("https://api.postforme.dev/**", async (route) => {
    await route.fulfill({
      status: 302,
      headers: { location: "http://localhost:8000/__sim__/pfm/consent?platform=instagram" },
    });
  });
  page = await context.newPage();
});

test.afterAll(async () => {
  await context.close();
});

const nav = (name: string) => page.locator("aside, nav").getByText(name, { exact: true }).first();

async function openSettings(section: string) {
  await nav("Settings").click();
  await page.getByRole("navigation", { name: "Settings sections" }).getByText(section, { exact: true }).click();
}

test("register and land in the app", async () => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Entra a Lumi" })).toBeVisible();
  await page.getByRole("button", { name: "No tengo cuenta" }).click();
  await page.getByLabel("Nombre").fill("Ana E2E");
  await page.getByLabel("Correo").fill(EMAIL);
  await page.getByLabel("Contraseña").fill(PASSWORD);
  await page.getByRole("button", { name: "Crear cuenta" }).click();
  await expect(page.getByRole("heading", { name: "Crea tu cuenta" })).toBeHidden();
  await expect(page.getByLabel("Prompt")).toBeVisible();
});

test("add a profile in Settings", async () => {
  await openSettings("Profile");
  await page.getByLabel("Usuario del nuevo perfil").fill("@demo");
  await page.getByRole("button", { name: "Añadir perfil" }).click();
  await expect(page.getByRole("list", { name: "Profiles" })).toContainText("@demo");
  await expect(page.getByText("Activo", { exact: true })).toBeVisible();
});

test("every provider shows its status; Google and X stay unconfigured", async () => {
  await openSettings("Connected Accounts");
  await expect(page.getByTestId("status-meta")).toHaveText("Sin conectar");
  await expect(page.getByTestId("status-pfm")).toHaveText("Sin conectar");
  // No keys in this environment: connect is disabled and the card says where to paste them.
  await expect(page.getByTestId("provider-x").getByText("lumi/.env")).toBeVisible();
  await expect(page.getByTestId("connect-x")).toBeDisabled();
});

test("connect Facebook from Settings: authorize, callback, return banner, status", async () => {
  await openSettings("Connected Accounts");
  await page.getByTestId("connect-meta").click();
  await expect(page.getByTestId("connect-return")).toContainText("Facebook conectado");
  await expect(page).toHaveURL(/^http:\/\/localhost:3010\/?$/); // the callback URL was cleaned
  await expect(page.getByTestId("status-meta")).toHaveText("Conectado");
  const card = page.getByTestId("provider-meta");
  await expect(card).toContainText("Pagina Uno");
  await expect(card).toContainText("Pagina Dos"); // the limited page is listed too
  await expect(card).not.toContainText("meta-page1-FAKE"); // no token ever reaches the browser
});

test("connect Post for Me: the sync on return mirrors the account", async () => {
  await openSettings("Connected Accounts");
  await page.getByLabel("Red social a conectar").selectOption("instagram");
  await page.getByTestId("connect-pfm").click();
  await expect(page.getByTestId("connect-return")).toContainText("Post for Me conectado");
  await expect(page.getByTestId("status-pfm")).toHaveText("Conectado");
  await expect(page.getByTestId("provider-pfm")).toContainText("instagram");
  // "Actualizar" on PFM is the POST sync. The account is still there afterwards.
  const sync = page.waitForRequest(
    (r) => r.method() === "POST" && r.url().endsWith("/connections/pfm/sync"),
  );
  await page.getByTestId("refresh-pfm").click();
  await sync;
  await expect(page.getByTestId("status-pfm")).toHaveText("Conectado");
  await expect(page.getByTestId("provider-pfm")).toContainText("instagram");
});

test("the user cancels on the provider: the frontend page burns the state and the banner explains", async () => {
  await openSettings("Connected Accounts");
  denyNextConsent = true;
  await page.getByTestId("connect-meta").click();
  await expect(page.getByTestId("connect-return")).toContainText("Cancelaste la autorización");
  await expect(page).toHaveURL(/^http:\/\/localhost:3010\/?$/);
  await expect(page.getByTestId("status-meta")).toHaveText("Conectado"); // untouched by the failed try
});

test("a chat turn answers, and a connect card opens the real authorize flow", async () => {
  await page.goto("/");
  await nav("Home").click();
  await page.getByLabel("Prompt").fill("hola lumi");
  await page.getByLabel("Send").click();
  await expect(page.getByText(/Respuesta del modelo simulado a: .*hola lumi/)).toBeVisible();

  // Facebook is connected at this point, so the real tool reports it instead of minting a link.
  await page.getByLabel("Prompt").fill("conecta mi cuenta");
  await page.getByLabel("Send").click();
  await expect(page.getByText("Esa cuenta ya está conectada.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Connect facebook" })).toHaveCount(0);

  // After a disconnect the same request yields a real authorize link.
  await openSettings("Connected Accounts");
  const meta = page.getByTestId("provider-meta");
  while ((await page.getByTestId("status-meta").textContent()) !== "Sin conectar") {
    await meta.getByRole("button", { name: "Desconectar" }).first().click();
    await page.waitForTimeout(300);
  }
  await nav("Home").click();
  await page.getByLabel("Prompt").fill("conecta mi cuenta otra vez");
  await page.getByLabel("Send").click();
  const link = page.getByRole("link", { name: "Connect facebook" });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", /facebook\.com\/v26\.0\/dialog\/oauth/);
  await expect(link).toHaveClass(/connectCard/); // marked by the tool result, not by its text

  // The model double saw the real registry (connect_account offered) and the real tool result.
  const calls: { tools: string[]; last_role: string }[] = await (await fetch("http://127.0.0.1:8099/_calls")).json();
  expect(calls.some((c) => c.tools.includes("connect_account"))).toBe(true);
  expect(calls.some((c) => c.last_role === "tool")).toBe(true);
});

test("publish: review without publishing, then really publish after confirming", async () => {
  // A login with several Pages cannot tell which one is this profile's, so reconnect with one.
  await page.request.get("http://localhost:8000/__sim__/meta/pages?n=1");
  await openSettings("Connected Accounts");
  const meta = page.getByTestId("provider-meta");
  while ((await page.getByTestId("status-meta").textContent()) !== "Sin conectar") {
    await meta.getByRole("button", { name: "Desconectar" }).first().click();
    await page.waitForTimeout(300);
  }
  await page.getByTestId("connect-meta").click();
  await expect(page.getByTestId("status-meta")).toHaveText("Conectado");
  await nav("Publish").click();
  await page.getByTestId("publish-source").fill("Lanzamos la versión nueva hoy");
  const networks = page.getByRole("group", { name: "Redes" });
  await networks.getByLabel("X", { exact: true }).uncheck();
  await networks.getByLabel("LinkedIn").uncheck();
  await networks.getByLabel("Facebook").check();
  await page.getByTestId("publish-manual").click();
  const card = page.getByTestId("draft-facebook");
  await expect(card).toBeVisible();
  await card.getByLabel("Texto para Facebook").fill("Lanzamos la versión nueva hoy");
  await card.getByTestId("publish-preview").click();
  await expect(card.getByTestId("preview-result")).toBeVisible();
  await expect(card.getByTestId("publish-result")).toHaveCount(0);

  await card.getByTestId("publish-start").click();
  await card.getByTestId("publish-confirm").click();
  await expect(card.getByTestId("publish-result")).toBeVisible();
});

test("link a Facebook Page to a Facebook profile, replace it, and see it refused on an X profile", async () => {
  // A login with two Pages stores both and links none: the user picks one per profile.
  await page.request.get("http://localhost:8000/__sim__/meta/pages?n=2");
  await openSettings("Profile");
  await page.getByLabel("Red del nuevo perfil").selectOption("facebook");
  await page.getByLabel("Usuario del nuevo perfil").fill("@pagina");
  await page.getByRole("button", { name: "Añadir perfil" }).click();
  const fbRow = page.getByRole("list", { name: "Profiles" }).getByRole("listitem").filter({ hasText: "@pagina" });
  await expect(fbRow).toBeVisible();
  if ((await fbRow.getByRole("button", { name: "Usar este" }).count()) > 0) {
    await fbRow.getByRole("button", { name: "Usar este" }).click();
  }
  await expect(fbRow.getByText("Activo", { exact: true })).toBeVisible();

  await openSettings("Connected Accounts");
  await page.getByTestId("connect-meta").click();
  await expect(page.getByTestId("connect-return")).toContainText("Facebook conectado");
  await openSettings("Connected Accounts");
  const meta = page.getByTestId("provider-meta");
  const uno = meta.getByRole("listitem").filter({ hasText: "Pagina Uno" });
  const dos = meta.getByRole("listitem").filter({ hasText: "Pagina Dos" });

  const linkCall = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith("/connections/meta/link"));
  await uno.getByRole("button", { name: "Usar para @pagina" }).click();
  const sent = (await linkCall).postDataJSON();
  expect(Object.keys(sent).sort()).toEqual(["account_id", "profile_id"]);
  await expect(uno).toContainText("Publica para @pagina");
  await expect(dos.getByRole("button", { name: "Usar para @pagina" })).toBeVisible();

  // Choosing the other Page replaces the first, which stays connected and can be chosen again.
  await dos.getByRole("button", { name: "Usar para @pagina" }).click();
  await expect(dos).toContainText("Publica para @pagina");
  await expect(page.getByTestId("note-meta")).toContainText("La anterior sigue conectada");
  await expect(uno.getByRole("button", { name: "Usar para @pagina" })).toBeVisible();
  await expect(page.getByTestId("status-meta")).toHaveText("Conectado");

  // The X profile cannot take a Facebook Page: the panel does not offer it.
  await openSettings("Profile");
  const xRow = page.getByRole("list", { name: "Profiles" }).getByRole("listitem").filter({ hasText: "@demo" });
  await xRow.getByRole("button", { name: "Usar este" }).click();
  await openSettings("Connected Accounts");
  await expect(uno).toContainText("Es de otra red");
  await expect(dos).toContainText("Es de otra red");
  await expect(meta.getByRole("button", { name: /Usar para/ })).toHaveCount(0);
});

test("disconnect Facebook, then sign out and back in", async () => {
  await openSettings("Connected Accounts");
  const card = page.getByTestId("provider-meta");
  // The Pages from the link test are still connected: disconnect them one by one.
  for (let i = 0; i < 6 && (await page.getByTestId("status-meta").textContent()) !== "Sin conectar"; i++) {
    await card.getByRole("button", { name: "Desconectar" }).first().click();
    await page.waitForTimeout(300);
  }
  await expect(page.getByTestId("status-meta")).toHaveText("Sin conectar");

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Entra a Lumi" })).toBeVisible();
  await page.getByLabel("Correo").fill(EMAIL);
  await page.getByLabel("Contraseña").fill("wrong-password-123");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("Contraseña").fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByLabel("Prompt")).toBeVisible();
});

test("a ?say= link never sends a chat turn on its own", async () => {
  // Opening the app only reads. Any write (a chat turn is a POST) means the query string drove it.
  const writes: string[] = [];
  const watch = (request: { url(): string; method(): string }) => {
    if (request.method() !== "GET") writes.push(`${request.method()} ${request.url()}`);
  };
  page.on("request", watch);
  await page.goto("/?say=hola-no-debe-enviarse");
  await page.waitForTimeout(2500);
  page.off("request", watch);
  expect(writes).toEqual([]);
  // The old handler also yanked the app to Settings while the profile was still loading.
  await expect(page.getByLabel("Prompt")).toBeVisible();
  await expect(page.getByLabel("Prompt")).toHaveValue("");
  await expect(page.getByText(/hola-no-debe-enviarse/)).toHaveCount(0);
});

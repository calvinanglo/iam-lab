import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const screenshotDir = resolve(__dirname, '..', 'docs', 'screenshots');
mkdirSync(screenshotDir, { recursive: true });

const KC_URL = 'https://keycloak.iam-lab.local:8443';
const GRAFANA_URL = 'https://grafana.iam-lab.local:3443';
const GITEA_URL = 'https://gitea.iam-lab.local:3444';
const ADMIN_USER = 'admin';
const ADMIN_PASS = 'AdminPass2024!';

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--ignore-certificate-errors']
  });

  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1920, height: 1080 }
  });

  // ── Keycloak Admin Login ──
  console.log('=== Keycloak Admin Screenshots ===');
  const kcPage = await context.newPage();

  // Screenshot: Keycloak login page
  console.log('Capturing: KC login page...');
  await kcPage.goto(`${KC_URL}/admin/master/console/`);
  await kcPage.waitForSelector('#username', { timeout: 15000 });
  await kcPage.screenshot({ path: resolve(screenshotDir, '00-keycloak-login.png') });
  console.log('  Saved: 00-keycloak-login.png');

  // Login
  await kcPage.fill('#username', ADMIN_USER);
  await kcPage.fill('#password', ADMIN_PASS);
  await kcPage.click('#kc-login');
  await kcPage.waitForURL('**/admin/master/console/**', { timeout: 15000 });

  // Navigate to enterprise realm and trigger LDAP sync
  console.log('Triggering LDAP sync...');
  // Get admin token
  const tokenResp = await kcPage.request.post(`${KC_URL}/realms/master/protocol/openid-connect/token`, {
    form: {
      client_id: 'admin-cli',
      username: ADMIN_USER,
      password: ADMIN_PASS,
      grant_type: 'password'
    }
  });
  const tokenData = await tokenResp.json();
  const token = tokenData.access_token;

  // Get LDAP component ID
  const compResp = await kcPage.request.get(
    `${KC_URL}/admin/realms/enterprise/components?type=org.keycloak.storage.UserStorageProvider`,
    { headers: { 'Authorization': `Bearer ${token}` } }
  );
  const components = await compResp.json();
  if (components.length > 0) {
    const compId = components[0].id;
    try {
      await kcPage.request.post(
        `${KC_URL}/admin/realms/enterprise/user-storage/${compId}/sync?action=triggerFullSync`,
        { headers: { 'Authorization': `Bearer ${token}` } }
      );
      console.log('  LDAP sync triggered');
    } catch (e) {
      console.log('  LDAP sync failed (may need correct bind password)');
    }
  }
  await kcPage.waitForTimeout(3000);

  // Screenshot: Users page (after sync)
  console.log('Capturing: Users page...');
  await kcPage.goto(`${KC_URL}/admin/master/console/#/enterprise/users`, { waitUntil: 'networkidle' });
  await kcPage.waitForTimeout(2000);
  try {
    const searchInput = kcPage.locator('input[placeholder="Search user"]');
    await searchInput.fill('*');
    await searchInput.press('Enter');
    await kcPage.waitForTimeout(3000);
  } catch (e) {}
  await kcPage.screenshot({ path: resolve(screenshotDir, '05-users.png') });
  console.log('  Saved: 05-users.png (updated)');

  // Screenshot: LDAP Mappers tab
  console.log('Capturing: LDAP Mappers...');
  await kcPage.goto(`${KC_URL}/admin/master/console/#/enterprise/user-federation`, { waitUntil: 'networkidle' });
  await kcPage.waitForTimeout(2000);
  try {
    await kcPage.click('text=ldap', { timeout: 5000 });
    await kcPage.waitForTimeout(2000);
    await kcPage.click('text=Mappers', { timeout: 5000 });
    await kcPage.waitForTimeout(2000);
  } catch (e) {
    console.log('  Could not navigate to Mappers tab');
  }
  await kcPage.screenshot({ path: resolve(screenshotDir, '14-ldap-mappers.png') });
  console.log('  Saved: 14-ldap-mappers.png');

  // Screenshot: Tokens/Sessions settings
  console.log('Capturing: Token settings...');
  await kcPage.goto(`${KC_URL}/admin/master/console/#/enterprise/realm-settings/tokens`, { waitUntil: 'networkidle' });
  await kcPage.waitForTimeout(2000);
  await kcPage.screenshot({ path: resolve(screenshotDir, '15-token-settings.png') });
  console.log('  Saved: 15-token-settings.png');

  // ── Grafana SSO Flow ──
  console.log('\n=== Grafana SSO Flow ===');
  const grafanaPage = await context.newPage();

  // Screenshot: Grafana login with SSO button
  console.log('Capturing: Grafana login page...');
  await grafanaPage.goto(GRAFANA_URL, { waitUntil: 'networkidle', timeout: 15000 });
  await grafanaPage.waitForTimeout(2000);
  await grafanaPage.screenshot({ path: resolve(screenshotDir, '12-grafana-sso.png') });
  console.log('  Saved: 12-grafana-sso.png (updated)');

  // Click SSO login button
  console.log('Capturing: SSO redirect to Keycloak...');
  try {
    await grafanaPage.click('a:has-text("Keycloak")', { timeout: 5000 });
    await grafanaPage.waitForTimeout(3000);
    await grafanaPage.screenshot({ path: resolve(screenshotDir, '16-grafana-sso-redirect.png') });
    console.log('  Saved: 16-grafana-sso-redirect.png');

    // Login via Keycloak with admin credentials
    console.log('Capturing: SSO login flow...');
    try {
      await grafanaPage.fill('#username', ADMIN_USER, { timeout: 3000 });
      await grafanaPage.fill('#password', ADMIN_PASS);
      await grafanaPage.click('#kc-login');
      await grafanaPage.waitForTimeout(5000);
      await grafanaPage.screenshot({ path: resolve(screenshotDir, '17-grafana-logged-in.png') });
      console.log('  Saved: 17-grafana-logged-in.png');

      // Navigate to IAM Operations dashboard
      console.log('Capturing: IAM Operations Dashboard...');
      await grafanaPage.goto(`${GRAFANA_URL}/d/iam-operations/iam-operations?orgId=1`, { waitUntil: 'networkidle', timeout: 15000 });
      await grafanaPage.waitForTimeout(5000);
      await grafanaPage.screenshot({ path: resolve(screenshotDir, '18-grafana-dashboard.png') });
      console.log('  Saved: 18-grafana-dashboard.png');

      // Scroll down for more panels
      await grafanaPage.evaluate(() => window.scrollBy(0, 600));
      await grafanaPage.waitForTimeout(2000);
      await grafanaPage.screenshot({ path: resolve(screenshotDir, '19-grafana-dashboard-panels.png') });
      console.log('  Saved: 19-grafana-dashboard-panels.png');

    } catch (e) {
      console.log('  SSO login flow: ' + e.message);
    }
  } catch (e) {
    console.log('  Could not find SSO button: ' + e.message);
  }

  // ── Gitea SSO Flow ──
  console.log('\n=== Gitea SSO Flow ===');
  const giteaPage = await context.newPage();

  console.log('Capturing: Gitea sign in page...');
  await giteaPage.goto(`${GITEA_URL}/user/login`, { waitUntil: 'networkidle', timeout: 15000 });
  await giteaPage.waitForTimeout(2000);
  await giteaPage.screenshot({ path: resolve(screenshotDir, '20-gitea-login.png') });
  console.log('  Saved: 20-gitea-login.png');

  // ── OIDC Discovery Endpoint ──
  console.log('\n=== OIDC Discovery ===');
  const oidcPage = await context.newPage();
  console.log('Capturing: OIDC Discovery endpoint...');
  await oidcPage.goto(`${KC_URL}/realms/enterprise/.well-known/openid-configuration`, { waitUntil: 'networkidle' });
  await oidcPage.waitForTimeout(1000);
  await oidcPage.screenshot({ path: resolve(screenshotDir, '21-oidc-discovery.png') });
  console.log('  Saved: 21-oidc-discovery.png');

  // ── Client Details (Grafana PKCE) ──
  console.log('\n=== Client PKCE Config ===');
  // Get grafana client ID
  const clientsResp = await kcPage.request.get(
    `${KC_URL}/admin/realms/enterprise/clients?clientId=grafana`,
    { headers: { 'Authorization': `Bearer ${token}` } }
  );
  const clients = await clientsResp.json();
  if (clients.length > 0) {
    const grafanaClientUuid = clients[0].id;
    console.log('Capturing: Grafana client settings...');
    await kcPage.goto(`${KC_URL}/admin/master/console/#/enterprise/clients/${grafanaClientUuid}/settings`, { waitUntil: 'networkidle' });
    await kcPage.waitForTimeout(2000);
    await kcPage.screenshot({ path: resolve(screenshotDir, '22-grafana-client-settings.png') });
    console.log('  Saved: 22-grafana-client-settings.png');

    // Scroll down to show PKCE settings
    await kcPage.evaluate(() => window.scrollBy(0, 800));
    await kcPage.waitForTimeout(1500);
    await kcPage.screenshot({ path: resolve(screenshotDir, '23-grafana-client-pkce.png') });
    console.log('  Saved: 23-grafana-client-pkce.png');
  }

  await browser.close();
  console.log('\nAll extra screenshots captured successfully!');
}

main().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});

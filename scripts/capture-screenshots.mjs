import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const screenshotDir = resolve(__dirname, '..', 'docs', 'screenshots');
mkdirSync(screenshotDir, { recursive: true });

const KC_URL = 'https://keycloak.iam-lab.local:8443';
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

  const page = await context.newPage();

  // Login to Keycloak
  console.log('Logging into Keycloak...');
  await page.goto(`${KC_URL}/admin/master/console/`);
  await page.waitForSelector('#username', { timeout: 15000 });
  await page.fill('#username', ADMIN_USER);
  await page.fill('#password', ADMIN_PASS);
  await page.click('#kc-login');
  await page.waitForURL('**/admin/master/console/**', { timeout: 15000 });
  console.log('Logged in successfully.');

  // Screenshot helper
  async function capture(name, url, waitFor) {
    console.log(`Capturing: ${name}...`);
    await page.goto(url, { waitUntil: 'networkidle' });
    if (waitFor) {
      await page.waitForTimeout(waitFor);
    } else {
      await page.waitForTimeout(2000);
    }
    await page.screenshot({ path: resolve(screenshotDir, name), fullPage: false });
    console.log(`  Saved: docs/screenshots/${name}`);
  }

  // 1. Enterprise Realm welcome
  await capture('01-enterprise-realm.png',
    `${KC_URL}/admin/master/console/#/enterprise`);

  // 2. Realm Roles
  await capture('02-realm-roles.png',
    `${KC_URL}/admin/master/console/#/enterprise/roles`);

  // 3. Groups
  await capture('03-groups.png',
    `${KC_URL}/admin/master/console/#/enterprise/groups`);

  // 4. Clients
  await capture('04-clients.png',
    `${KC_URL}/admin/master/console/#/enterprise/clients`);

  // 5. Users - search for *
  console.log('Capturing: 05-users.png...');
  await page.goto(`${KC_URL}/admin/master/console/#/enterprise/users`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  try {
    const searchInput = page.locator('input[placeholder="Search user"]');
    await searchInput.fill('*');
    await searchInput.press('Enter');
    await page.waitForTimeout(3000);
  } catch (e) {
    console.log('  Could not search users, taking screenshot as-is');
  }
  await page.screenshot({ path: resolve(screenshotDir, '05-users.png'), fullPage: false });
  console.log('  Saved: docs/screenshots/05-users.png');

  // 6. User Federation
  await capture('06-user-federation.png',
    `${KC_URL}/admin/master/console/#/enterprise/user-federation`);

  // 7. LDAP Settings (click into LDAP provider)
  console.log('Capturing: 07-ldap-settings.png...');
  await page.goto(`${KC_URL}/admin/master/console/#/enterprise/user-federation`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  try {
    await page.click('text=ldap', { timeout: 5000 });
    await page.waitForTimeout(2000);
  } catch (e) {
    console.log('  Could not click LDAP provider');
  }
  await page.screenshot({ path: resolve(screenshotDir, '07-ldap-settings.png'), fullPage: false });
  console.log('  Saved: docs/screenshots/07-ldap-settings.png');

  // 8. Security Defenses - Headers
  await capture('08-security-headers.png',
    `${KC_URL}/admin/master/console/#/enterprise/realm-settings/security-defenses`);

  // 9. Brute Force Detection
  console.log('Capturing: 09-brute-force.png...');
  await page.goto(`${KC_URL}/admin/master/console/#/enterprise/realm-settings/security-defenses`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  try {
    await page.click('text=Brute force detection', { timeout: 5000 });
    await page.waitForTimeout(1500);
  } catch (e) {
    console.log('  Could not click Brute force tab');
  }
  await page.screenshot({ path: resolve(screenshotDir, '09-brute-force.png'), fullPage: false });
  console.log('  Saved: docs/screenshots/09-brute-force.png');

  // 10. Events configuration
  await capture('10-events.png',
    `${KC_URL}/admin/master/console/#/enterprise/realm-settings/events`);

  // 11. Authentication flows
  await capture('11-authentication.png',
    `${KC_URL}/admin/master/console/#/enterprise/authentication`);

  // 12. Grafana login page (redirects to KC)
  console.log('Capturing: 12-grafana-sso.png...');
  const grafanaPage = await context.newPage();
  await grafanaPage.goto('https://grafana.iam-lab.local:3443', { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
  await grafanaPage.waitForTimeout(3000);
  await grafanaPage.screenshot({ path: resolve(screenshotDir, '12-grafana-sso.png'), fullPage: false });
  console.log('  Saved: docs/screenshots/12-grafana-sso.png');

  // 13. Gitea login page
  console.log('Capturing: 13-gitea.png...');
  const giteaPage = await context.newPage();
  await giteaPage.goto('https://gitea.iam-lab.local:3444', { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
  await giteaPage.waitForTimeout(3000);
  await giteaPage.screenshot({ path: resolve(screenshotDir, '13-gitea.png'), fullPage: false });
  console.log('  Saved: docs/screenshots/13-gitea.png');

  await browser.close();
  console.log('\nAll screenshots captured successfully!');
  console.log(`Output directory: ${screenshotDir}`);
}

main().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});

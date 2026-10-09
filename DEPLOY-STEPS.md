# Deploy Harvest to Google Cloud: step by step

Follow the steps in order. Every command block says where to run it.
For the reasoning behind each step, automation and troubleshooting, see [DEPLOY.md](DEPLOY.md).

**You need:** a Google account, a credit or debit card (for billing), and a Gemini API key.
About 30 minutes the first time.

---

## Part A. In the browser (5 minutes)

**A1. Get a Gemini API key.**
Open https://aistudio.google.com/apikey, click *Create API key* and copy it. Keep it somewhere
safe; you paste it in step B6.

**A2. Create a Google Cloud project.**
1. Open https://console.cloud.google.com and sign in.
2. Click the project picker at the top, then *New project*.
3. Name it, for example `harvest-demo`, and click *Create*.
4. Write down the **Project ID** shown under the name (for example `harvest-demo-123456`).
   It is not the same as the name. You will use it as `PROJECT` below.

**A3. Link billing.**
Open https://console.cloud.google.com/billing, create or choose a billing account, and link it
to your project. Cloud Run will not deploy without it. New accounts usually get free trial credit.

**A4. Open Cloud Shell.**
In the console, click the `>_` icon at the top right. A terminal opens at the bottom of the page.
It already has `gcloud`, Node and git, and you are already signed in. **Run every command in
Parts B to D here.**

---

## Part B. One-time setup (in Cloud Shell, 10 minutes)

**B1. Get the code.**
```bash
git clone https://github.com/RaymonddC/Harvest.git
cd Harvest
```

**B2. Set your variables.** Replace the project id with yours from A2.
```bash
export PROJECT=your-project-id
export REGION=asia-southeast1
gcloud config set project $PROJECT
```
> These variables are lost when Cloud Shell closes. If you come back later, run these three
> lines again, from inside the `Harvest` folder.

**B3. Turn on the services and create the database.**
```bash
gcloud services enable run.googleapis.com firestore.googleapis.com secretmanager.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com logging.googleapis.com \
  firebase.googleapis.com cloudresourcemanager.googleapis.com
gcloud firestore databases create --location=$REGION --type=firestore-native
```
If it says the database already exists, that is fine.

**B4. Install the Firebase CLI and sign in.**
```bash
npm install -g firebase-tools
firebase login --no-localhost
```
Open the link it prints, approve, and paste the code back into the terminal.
If `firebase: command not found` appears later, run `export PATH=$PATH:$(npm prefix -g)/bin`.

**B5. Add Firebase to your project** (needed for Hosting).
```bash
firebase projects:addfirebase $PROJECT
```
If it says the project already has Firebase, that is fine. If it fails with `403 ... Firebase Management
API has not been used`, the API from B3 is not active yet: wait a minute and run it again.

**B6. Save the Gemini key in Secret Manager.**
```bash
read -rs GEMINI_KEY        # paste the key from A1, press Enter (nothing is shown as you type)
printf '%s' "$GEMINI_KEY" | gcloud secrets create gemini-api-key --data-file=-
unset GEMINI_KEY
```

**B7. Let the Cloud Run service read Firestore and that secret.**
```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
RUNTIME_SA=$PROJECT_NUMBER-compute@developer.gserviceaccount.com
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$RUNTIME_SA \
  --role=roles/datastore.user --condition=None
gcloud secrets add-iam-policy-binding gemini-api-key --member=serviceAccount:$RUNTIME_SA \
  --role=roles/secretmanager.secretAccessor
```

**B8. Tell the Firebase CLI which project to use.**
```bash
cp .firebaserc.example .firebaserc
sed -i "s/your-gcp-project-id/$PROJECT/" .firebaserc
cat .firebaserc        # should show your project id
```

Part B is done. You never repeat it for this project.

---

## Part C. Deploy (in Cloud Shell, 5 to 10 minutes)

**C1. Choose a planner password.** It protects the approve, reject and campaign buttons.
```bash
export PLANNER_TOKEN=choose-a-password-here
```
Remember it. You type it into the dashboard once, and every later deploy must use the same one.

**C2. Run the deploy script.**
```bash
bash deploy/deploy.sh
```
- When it asks `Do you want to continue (Y/n)?` about creating an Artifact Registry
  repository, answer `Y`.
- The first build takes several minutes.
- At the end it prints the gateway URL, then the dashboard and call-client URLs.

---

## Part D. Check it works

**D1. Health check.**
```bash
curl "$(gcloud run services describe harvest-gateway --region $REGION --format 'value(status.url)')/healthz"
```
You should see `{"ok":true,"store":"firestore", ...}`.

**D2. Open the pages** (replace the project id):
- Planner setup: `https://YOUR-PROJECT-ID.web.app/setup.html`
- Live forecast: `https://YOUR-PROJECT-ID.web.app/`
- Approvals: `https://YOUR-PROJECT-ID.web.app/approvals.html`
- Call client: `https://YOUR-PROJECT-ID.web.app/call.html` (allow the microphone; use headphones)

**D3. Try the demo.** On the setup page click *Start campaign*. When you press a button the
dashboard asks for the planner password from C1. Then follow the demo walk-through in the README.

---

## Part E. Redeploying later

For a code change, run this from the `Harvest` folder in Cloud Shell:
```bash
git pull
export PROJECT=your-project-id REGION=asia-southeast1 PLANNER_TOKEN=the-same-password
SEED_DEMO_DATA=false SKIP_API_ENABLE=true bash deploy/deploy.sh
git checkout web/config.js
```
`SEED_DEMO_DATA=false` matters: without it the script wipes your data and reloads the demo data.

To deploy automatically on every push to `main`, follow section 7 of [DEPLOY.md](DEPLOY.md).
Do Parts A to D first.

---

## Part F. Stop paying for it

The gateway keeps one instance running all day. When you are not using it:
```bash
gcloud run services update harvest-gateway --region $REGION --min-instances 0
```
To remove everything, delete the project in the console (*IAM and admin, Settings, Shut down*).

---

## If something fails

| Message | Fix |
|---|---|
| `billing account ... not found` or Cloud Run API cannot be enabled | Billing is not linked to the project (A3). |
| `PERMISSION_DENIED` from `gcloud` | Make sure you are signed in as the account that owns the project: `gcloud auth list`. |
| `firebase: command not found` | `export PATH=$PATH:$(npm prefix -g)/bin` |
| `addfirebase` fails with `403 Firebase Management API has not been used` | `gcloud services enable firebase.googleapis.com cloudresourcemanager.googleapis.com`, wait a minute, run B5 again. |
| Firebase says the project is not a Firebase project | Run B5 again. |
| Health check returns an error, or the logs mention Firestore permissions | Run B7 again. |
| Voice call fails straight away | The secret is missing or the key is wrong (B6). Check `gcloud run services logs read harvest-gateway --region $REGION --limit 50`. |
| Organization policy blocks `--allow-unauthenticated` | Your Google account belongs to a company or school that forbids public Cloud Run services. Use a personal Google account and project. |

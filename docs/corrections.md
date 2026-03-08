# Config Corrections

Corrections applied after verifying team and engineer data against the live GitLab API
(queried via `PRIVATE-TOKEN` on 2026-02-22). Each section documents what changed versus
the placeholder values generated from names alone.

---

## Domain: `marketing` (`config/domains/marketing.yaml`)

### Pattern corrections that apply to all marketing teams

| Pattern | Cause | Fix |
|---------|-------|-----|
| Sinch SAML accounts use `CamelCase` usernames (e.g. `Anton.Gorbylev`) | Sinch SSO provisions accounts with `Firstname.Lastname` casing | Always check actual username via API; do not derive from email |
| Numeric suffix `2` / `1` on usernames (e.g. `nhut.le2`, `an.luu2`) | Collision with pre-existing public GitLab account | Cannot be predicted from name — must verify via API |
| GitLab display name ≠ common name (e.g. "Adrian Nguyen" = Anh Nguyen) | SSO syncs legal/English name; team uses preferred name | Cross-reference by username, not display name |
| Two base paths exist: `smb/teams/` and `applications/teams/` | SMB = legacy Ecosystem products; `applications/teams/` = newer Engage/ST products | CMX/CONTACTS/EN are under `smb/teams/`; ECC/STM are under `applications/teams/` |
| Domain misattribution | Teams were initially assigned to `marketing` by default | CONTACTS belongs to `conversations` domain; EN/thor belongs to `apps-core` domain — both temporarily parked in `marketing` |

---

### Team: CMX — Customer Analytics & Reporting

**GitLab group:** `sinch/sinch-projects/applications/smb/teams/customer_reporting`
_(Note: an older group `conv_starter` exists with identical members — `customer_reporting` is the current canonical group)_

| Field | Placeholder | Corrected | Source |
|-------|-------------|-----------|--------|
| `gitlab_path` | `null` | `sinch/sinch-projects/applications/smb/teams/customer_reporting` | GitLab API subgroup list |
| Anh Nguyen `username` | `anh.nguyen` | `anh.nguyenvuphuong` | GitLab group members |
| Loi Letan `username` | `loi.letan` | `loilet` | GitLab group members |
| Nhut Le `username` | `nhut.le` | `nhut.le2` | GitLab group members (suffix collision) |
| Nguyen Thi My Duyen `username` | `duyen.nguyenthimy` | `Nguyen.Thi.My.Duyen` | GitLab group members (SAML CamelCase) |
| `headcount` | 7 | 8 | Raymond Burgess (manager) found in group |

**Members added (not in original roster):**
- Raymond Burgess `@Raymond.Burgess` — Owner-role member, marked `role: manager, exclude_from_metrics: true`

**Members confirmed correct:** `hoang.vohuy`, `phuoc.nguyendang`, `tri.nguyenviet`

---

### Team: ECC — Campaigns

**GitLab group:** `sinch/sinch-projects/applications/teams/campaign-creation`
_(Under `applications/teams/`, NOT `smb/teams/` — different branch of the GitLab namespace)_

| Field | Placeholder | Corrected | Source |
|-------|-------------|-----------|--------|
| `gitlab_path` | `null` | `sinch/sinch-projects/applications/teams/campaign-creation` | Rodolfo Bitu's contributed projects |
| Priscila Pereira Lima `username` | `priscila.pereiralima` | `priscila.lima2` | GitLab group members |
| Thiago Medina de Oliveira `username` | `thiago.medina` | `thiago.medina1` | GitLab group members (suffix collision) |
| Jéssyca Noronha `username` | `jessyca.noronha` | `jessyca.noronha` | ✓ Correct as derived |

**Members confirmed correct:** `rodolfo.bitu`, `jessyca.noronha`

---

### Team: CONTACTS — Contacts (Marketing)

**GitLab group:** `sinch/sinch-projects/applications/smb/teams/contacts`

| Field | Placeholder | Corrected | Source |
|-------|-------------|-----------|--------|
| `gitlab_path` | `null` | `sinch/sinch-projects/applications/smb/teams/contacts` | GitLab API subgroup list |
| Piedad Sánchez `username` | `piedad.sanchez` | `piedad.sanchez` | ✓ Correct as derived |
| `headcount` | 1 | 7 | 6 engineers discovered in GitLab group |
| `effective_engineers` | 0 | 6 | Same discovery |

**Engineers not in original roster — discovered via GitLab group members:**

| Name | GitLab username | Role |
|------|-----------------|------|
| João Francisco Santos | `@joaofranciscosantos` | engineer |
| Julia Mersing Ortiz | `@maria.juliaortiz` | engineer |
| Juan Manuel Meza Blanco | `@juan.manuel.meza.blanco` | engineer |
| Alberto Pérez Navarro | `@alberto.pereznavarro` | engineer |
| Oscar Quintana Méndez | `@oscar.mendez1` | engineer |
| David Arce | `@david.arce1` | engineer |

> **Action required:** Confirm with Piedad Sánchez that these 6 people are active team members
> (they appear as Owners in the GitLab group, which may indicate they're tech leads or maintainers
> rather than individual contributors).

---

### Team: EN — Engage Growth

**GitLab group:** `sinch/sinch-projects/applications/smb/teams/thor`
_(Group is named "thor" — no "en" or "engage" group exists at this path)_

| Field | Placeholder | Corrected | Source |
|-------|-------------|-----------|--------|
| `gitlab_path` | `null` | `sinch/sinch-projects/applications/smb/teams/thor` | GitLab API subgroup list + member cross-reference |
| Hung Nguyendang `username` | `hung.nguyendang` | `hung.nguyendang1` | GitLab group members (`thor`) |
| An Luu `username` | `an.luu` | `an.luu2` | GitLab MR activity (`onboarding_accounts`) |
| Hien Nguyenthi `username` | `hien.nguyenthi` | `hien.nguyenthi1` | GitLab group members (`thor`), also known as "Katty" |
| Nguyen Sang Sinh `username` | `nguyen.sangsinh` | `nguyensang.sinh` | GitLab MR activity |

**Members confirmed correct:** `hau.tranlecong`, `phat.truongtuan`, `vu.nguyenhoanglinh`

**Note:** An Luu (`@an.luu2`) and Nguyen Sang Sinh (`@nguyensang.sinh`) are not direct members
of the `thor` group but appear in `onboarding_accounts` MR activity — they are confirmed EN team
engineers based on MR authorship pattern.

---

### Team: STM — SimpleTexting ST Engineering

**GitLab group:** `sinch/sinch-projects/applications/teams/simpletexting`
_(Under `applications/teams/`, NOT `smb/teams/` — SimpleTexting was acquired and has its own namespace branch)_

| Field | Placeholder | Corrected | Source |
|-------|-------------|-----------|--------|
| `gitlab_path` | `null` | `sinch/sinch-projects/applications/teams/simpletexting` | Sergey Yurov's contributed projects |
| Sergey Yurov `username` | `sergey.yurov` | `Sergey.Yurov1` | GitLab MR activity (SAML account uses `1` suffix) |
| Anton Bachevsky `username` | `anton.bachevsky` | `Anton.Bachevsky` | GitLab MR activity (CamelCase SAML) |
| Nikita Kapustin `username` | `nikita.kapustin` | `Nikita.Kapustin` | GitLab MR activity (CamelCase SAML) |
| Anastasia Shikova `username` | `anastasia.shikova` | `Anastasia.Shikova` | GitLab MR activity (CamelCase SAML) |
| Sergey Goldshteyn `username` | `sergey.goldshteyn` | `Sergey.Goldshteyn` | GitLab MR activity (CamelCase SAML) |
| Andrey Chekrygin `username` | `andrey.chekrygin` | `Andrey.Chekrygin` | GitLab MR activity (CamelCase SAML) |
| Vladimir Korovin `username` | `vladimir.korovin` | `Vladimir.Korovin` | GitLab MR activity (CamelCase SAML) |
| Denis Volkov `username` | `denis.volkov` | `Denis.Volkov1` | GitLab group direct members (`1` suffix) |
| Oleksandr Yanushkevych `username` | `oleksandr.yanushkevych` | `Alexander.Yanushkevych` | GitLab group direct members (Anglicised spelling) |
| Ivan Sobolevskii `username` | `ivan.sobolevskii` | **⚠ TODO** | Not found in GitLab MR activity or user search |

**⚠ Unresolved: Ivan Sobolevskii**
- Not present in `simpletexting` group MR activity (last 12 months)
- GitLab user search for "sobolevs" returns no Sinch SAML account
- Possible causes: departed, inactive, or uses a different name/handle in GitLab
- **Action required:** Verify with Anton Gorbylev whether Ivan is still on the team and what his GitLab username is

---

## Domain: `sinch-ecosystem` (`config/domains/sinch-ecosystem.yaml`)

No corrections required — this domain was not modified. All GitLab usernames were previously
verified through operational use.

---

## Domain attribution corrections (2026-02-22)

These corrections clarify which domain each team actually belongs to. Teams are temporarily
retained in `marketing.yaml` until their home domain configs are created.

### Team: CONTACTS — belongs to `conversations` domain

| Item | Initial assumption | Correct |
|------|-------------------|---------|
| Domain | `marketing` | `conversations` |
| Target config | `config/domains/marketing.yaml` | `config/domains/conversations.yaml` (not yet created) |
| Action | Parked in `marketing` with `⚠ TODO` comment | Move when `conversations` domain is set up |

### Team: EN (Engage Growth) — belongs to `apps-core` domain

| Item | Initial assumption | Correct |
|------|-------------------|---------|
| Domain | `marketing` | `apps-core` |
| Target config | `config/domains/marketing.yaml` | `config/domains/apps-core.yaml` (not yet created) |
| `gitlab_path` | `sinch/sinch-projects/applications/smb/teams/thor` | `sinch/sinch-projects/applications/smb/teams/onboarding_accounts` |
| Action | Parked in `marketing` with `⚠ TODO` comment | Move when `apps-core` domain is set up |

**Why `thor` was wrong:** The `thor` GitLab group is owned by the apps-core domain and contains
overlapping members, but it is not the canonical group for the Engage Growth team. The correct
group is `onboarding_accounts`, which is the team's primary project space.

### Domain migration completed (2026-02-22)

Both domain configs have been created. CONTACTS and EN have been removed from `marketing.yaml`.

| Domain slug | Config file | Teams |
|-------------|-------------|-------|
| `conversations` | `config/domains/conversations.yaml` | CONTACTS |
| `apps-core` | `config/domains/apps-core.yaml` | ICA, ACME, MAPI, ST |
| `marketing` | `config/domains/marketing.yaml` | CMX, ECC, STM, EN |

---

## Domain: `apps-core` (`config/domains/apps-core.yaml`)

Created 2026-02-22. All usernames verified via live GitLab API.

### Team: ICA — Customer Accounts

**GitLab group:** `sinch/sinch-projects/applications/smb/teams/customer_accounts`

| Field | Value | Source |
|-------|-------|--------|
| `gitlab_path` | `sinch/sinch-projects/applications/smb/teams/customer_accounts` | GitLab API group members |
| Tuan Do `username` | `tuandotony` | GitLab group MR activity |
| Tai To `username` | `tai.to` | GitLab group members |
| Duc Truong `username` | `duc.truongtan` | GitLab group members |
| Hien Huynh The `username` | `hienhuynhthe` | GitLab group members |
| Huy Le Vu Anh `username` | `HuyLe.VuAnh` | GitLab group members (CamelCase SAML) |
| Quang Nguyen Dang `username` | `quang.nguyen28` | GitLab group MR activity (numeric suffix collision) |

---

### Team: ACME — Messaging

**GitLab group:** `sinch/sinch-projects/applications/smb/teams/messaging_connectivity`

| Field | Value | Source |
|-------|-------|--------|
| `gitlab_path` | `sinch/sinch-projects/applications/smb/teams/messaging_connectivity` | GitLab API group members |
| Amila Chandrasiri `username` | `amila.chandrasiri` | GitLab group members |
| Archwin Dychingco `username` | `Archwin.Dychingco` | GitLab group members (CamelCase SAML) |
| Martin Shergold `username` | `Martin.Shergold` | GitLab group members (CamelCase SAML) |
| Julia Meng `username` | `Julia.Meng` | GitLab group members (CamelCase SAML) |

---

### Team: MAPI — Messaging APIs

**GitLab group:** `sinch/sinch-projects/applications/smb/teams/messaging_apis`

| Field | Value | Source |
|-------|-------|--------|
| `gitlab_path` | `sinch/sinch-projects/applications/smb/teams/messaging_apis` | GitLab API group members |
| Shravan Gurrala `username` | `Shravan.Gurrala1` | GitLab group members (CamelCase + suffix) |
| Shilpa Sadashivaiah `username` | `shilpa.sadashivaiah` | GitLab group members |
| Ofego Edafe `username` | `ofego.edafe` | GitLab group members |
| Jason Wu `username` | `Jason.Wu2` | GitLab group members (CamelCase + suffix) |
| Paul Sugiarto `username` | `Paulus.Sugiarto` | GitLab group members (CamelCase; given name differs) |
| Nick Bagga `username` | `nick.bagga` | GitLab group members |

---

### Team: ST — Senders & Tooling

**GitLab group:** `sinch/sinch-projects/applications/smb/teams/hammer`
_(Group is named "hammer" — the team's internal code name)_

| Field | Value | Source |
|-------|-------|--------|
| `gitlab_path` | `sinch/sinch-projects/applications/smb/teams/hammer` | GitLab API group members |
| Charith Haputhanthree `username` | `charith.haputhanthree` | GitLab group members |
| Vinh Hoang `username` | `vinh.hoang3` | GitLab group MR activity (numeric suffix) |
| Tri Huynh `username` | `tri.huynh3` | GitLab group MR activity (numeric suffix) |
| Pedro Moraes `username` | `pedro.moraes1` | GitLab group MR activity (numeric suffix) |
| Thinh Tran Hung `username` | `thinh.tranhung1` | GitLab group MR activity (numeric suffix) |

---

## Domain: `conversations` (`config/domains/conversations.yaml`)

Created 2026-02-22. CONTACTS team moved from `marketing.yaml`.
All usernames were previously verified — see marketing domain corrections above.

---

## Summary of verification method

All corrections were derived from live GitLab API queries on 2026-02-22:

1. **Group member list** — `GET /api/v4/groups/{id}/members` (direct members only)
2. **MR activity** — `GET /api/v4/groups/{id}/merge_requests?scope=all` (confirms active contributors)
3. **User search** — `GET /api/v4/users?search={term}` (disambiguates duplicate names)
4. **Contributed projects** — `GET /api/v4/users/{username}/contributed_projects` (traces which namespace engineers work in)

Credentials used: `GITLAB_TOKEN` env var (same token configured in `.env`).

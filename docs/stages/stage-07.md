# Stage 7: Onboarding and AML

Goal: a new client goes through a checklist, signs an engagement letter on screen, is identified and risk-assessed, and cannot be made live until that is done. Existing clients have a review cycle.

Read first: `docs/specs/06-onboarding-and-aml.md`. For signing links, reuse the action links built in Stage 9.

This stage is large. Build in the order below and commit after each item. If the session runs short, items 1 to 6 are the core.

## Build

1. Onboarding checklist: `OnboardingItem`, the template in Settings, creation when status becomes `onboarding` (hook into `on_proposal_accepted` and the manual status change), the client Onboarding tab, and the "Make live" gate with the owner override. Section 1.

2. Engagement letters: the parts in Settings, `EngagementLetter`, prepare and preview, send through the queue, the signing page, the signed PDF with its final page, saving to Documents, the review date and its task. Show letters on the client Engagement tab beside proposals. Section 2. Seed placeholder wording with the banner.

3. Identity checks: `IdentityCheck`, the proposed list of people, the form with the method list, uploads as sensitive documents, the expiry notice, and the checklist tick. Section 3. Include the small `IdentityProvider` interface with no provider behind it.

4. Risk assessment: `RiskQuestion` and `RiskAssessment`, Settings for questions and score bands, the assessment form, scoring, the level rules, approval, the Companies House snapshot on approval, and the review date. Seed the questions exactly as written in section 4.

5. The client Risk tab, and the AML badge on the client header.

6. Ongoing review, section 5: the review task job, the prompts from Companies House changes and new services, starting a review from the previous answers, the AML register under Reports with export, and the practice records in Settings.

7. HMRC authorisations, section 6: the model, the client HMRC tab, expiry dates, the notice job, and the checklist tick.

8. Professional clearance, section 7: the model, the letter template through the queue with a PDF copy, and the chase prompt.

9. Retention dates: when a client becomes former, set the end date and `retain_until` from the settings.

10. Overview panels: onboarding in progress, AML reviews due, authorisations expiring.

11. Demo data: three clients part-way through onboarding at different points, one high-risk assessment awaiting approval, a spread of risk levels and review dates across live clients, a few authorisations about to expire.

## Checks

- `make lint` and `make test` pass.
- Every test in section 8 of the spec exists.
- Also: the checklist items ticked by the system are ticked by the right events; making live activates proposed services and creates deadlines; a changed risk question is logged; the register export is owner only; `retain_until` is set from the settings.
- Screenshots in `docs/screens/stage-07/`: the Onboarding tab, the signing page on a phone-width screen, the risk assessment form, the Risk tab, the AML register.
- In the pull request, remind the user that the practice owner should read the risk questions and score bands before they are relied on.

## Not in this stage

A paid identity-check service. A direct HMRC link. The portal form for client details (Stage 10). Until then staff tick "Client details form completed" by hand.

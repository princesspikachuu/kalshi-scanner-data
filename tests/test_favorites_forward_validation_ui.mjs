import test from 'node:test';
import assert from 'node:assert/strict';
import {favoriteForwardValidationMarkup} from '../apps/web/shadow-view.mjs';

const cohort=(overrides={})=>({
  category:'commodities-15m',
  price_band_cents:70,
  time_bucket:'10–15m',
  independent_held_return_events:0,
  estimated_held_return_events:0,
  incomplete_settled_events:0,
  held_roi_mean_pct:null,
  held_roi_ci90_low_pct:null,
  held_roi_ci90_high_pct:null,
  confidence_status:'under_minimum',
  ...overrides,
});
const report=(rows,overrides={})=>({
  basis:'regular_favorites_forward_event_date_proxy',
  holdout_event_label_after:'2026-11-22',
  confidence_target:50,
  cells:rows,
  ...overrides,
});

test('forward-only Favorites cohorts are visible even at zero settled events',()=>{
  const html=favoriteForwardValidationMarkup(report([
    cohort(),cohort({category:'commodities-15m',price_band_cents:75}),
    cohort({category:'crypto-15m',price_band_cents:70,time_bucket:'5–10m'}),
    cohort({category:'finance-15m',price_band_cents:75}),
  ]));
  assert.match(html,/Forward validation · 4 fixed cohorts/);
  assert.match(html,/2026-11-22/);
  assert.match(html,/0\/50/);
  assert.match(html,/Commodities · 15m/);
  assert.match(html,/Finance · 15m/);
  assert.match(html,/Crypto · 15m/);
  assert.match(html,/0 estimated · 0 incomplete/);
  assert.match(html,/date proxy/);
  assert.match(html,/not multiple-testing adjusted/);
  assert.doesNotMatch(html,/profit-positive|profit-negative/);
});

test('forward ROI explicitly expects no new maker fees but retains recorded historical costs',()=>{
  const html=favoriteForwardValidationMarkup(report([cohort({
    independent_held_return_events:50,held_roi_mean_pct:'6',
    held_roi_ci90_low_pct:'1',held_roi_ci90_high_pct:'11',
    confidence_status:'available',
  })]));
  assert.match(html,/New regular Favorites entries require verified \$0 maker fees/);
  assert.match(html,/held to settlement/);
  assert.match(html,/Historical returns preserve recorded entry costs, including any older fees/);
  assert.match(html,/no new fees are assumed/);
  assert.match(html,/nonzero fee on a new maker fill requires investigation/);
  assert.doesNotMatch(html,/after entry costs\/fees/);
});

test('49 returns suppress stale numeric intervals and cannot imply profitable validation',()=>{
  const html=favoriteForwardValidationMarkup(report([cohort({
    independent_held_return_events:49,
    held_roi_mean_pct:'17.3',held_roi_ci90_low_pct:'5.7',
    held_roi_ci90_high_pct:'28.9',confidence_status:'available',
  })]));
  assert.match(html,/\+17\.30%/);
  assert.match(html,/Pending 49\/50/);
  assert.match(html,/Not yet established/);
  assert.doesNotMatch(html,/5\.70% to 28\.90%/);
  assert.doesNotMatch(html,/profit-positive/);
});

test('50 independent gains and losses with positive CI are signaled using lower bound',()=>{
  const html=favoriteForwardValidationMarkup(report([cohort({
    independent_held_return_events:50,
    estimated_held_return_events:7,
    incomplete_settled_events:2,
    held_roi_mean_pct:'12.34',
    held_roi_ci90_low_pct:'1.20',
    held_roi_ci90_high_pct:'23.48',
    confidence_status:'available',
  })]));
  assert.match(html,/50\/50/);
  assert.match(html,/7 estimated · 2 incomplete/);
  assert.match(html,/1\.20% to 23\.48%/);
  assert.match(html,/Entirely above 0%/);
  assert.match(html,/class="profit-positive"/);
});

test('negative and zero-crossing intervals remain distinct',()=>{
  const negative=favoriteForwardValidationMarkup(report([cohort({
    independent_held_return_events:51,
    held_roi_mean_pct:'-15.00',
    held_roi_ci90_low_pct:'-24',
    held_roi_ci90_high_pct:'-1',
    confidence_status:'available',
  })]));
  assert.match(negative,/Entirely below 0%/);
  assert.match(negative,/class="profit-negative"/);
  const cross=favoriteForwardValidationMarkup(report([cohort({
    independent_held_return_events:60,
    held_roi_mean_pct:'4.00',
    held_roi_ci90_low_pct:'-2',
    held_roi_ci90_high_pct:'10',
    confidence_status:'available',
  })]));
  assert.match(cross,/Includes 0%/);
  assert.doesNotMatch(cross,/class="profit-positive"/);
});

test('all-winner, missing outcome, malformed interval and old server stay conservative',()=>{
  const noLoss=favoriteForwardValidationMarkup(report([cohort({
    independent_held_return_events:50,
    held_roi_mean_pct:'35',
    held_roi_ci90_low_pct:'35',
    held_roi_ci90_high_pct:'35',
    confidence_status:'insufficient_gain_loss_variation',
  })]));
  assert.match(noLoss,/Need observed gains and losses/);
  assert.doesNotMatch(noLoss,/profit-positive/);
  const invalid=favoriteForwardValidationMarkup(report([cohort({
    independent_held_return_events:60,
    held_roi_mean_pct:'21',
    held_roi_ci90_low_pct:'NaN',
    held_roi_ci90_high_pct:'29',
    confidence_status:'available',
  })]));
  assert.match(invalid,/Unavailable/);
  assert.doesNotMatch(invalid,/profit-positive/);
  const reversed=favoriteForwardValidationMarkup(report([cohort({
    independent_held_return_events:60,
    held_roi_mean_pct:'21',
    held_roi_ci90_low_pct:'29',
    held_roi_ci90_high_pct:'12',
    confidence_status:'available',
  })]));
  assert.match(reversed,/Unavailable/);
  assert.equal(favoriteForwardValidationMarkup(null),'');
  assert.equal(favoriteForwardValidationMarkup({cells:[cohort()]}),'');
  assert.equal(favoriteForwardValidationMarkup(report([],{basis:'wrong_scope'})),'');
});

test('backend cohort labels are escaped; no raw event ids or market tickers appear',()=>{
  const html=favoriteForwardValidationMarkup(report([cohort({
    category:'<img src=x onerror=alert(1)>',
    time_bucket:'<script>alert(1)</script>',
  })]));
  assert.doesNotMatch(html,/<img|<script>/);
  assert.match(html,/&lt;img/);
  assert.match(html,/&lt;script/);
  assert.doesNotMatch(html,/KXGOLD15M-/);
});

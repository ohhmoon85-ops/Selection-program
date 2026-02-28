"""
한영자 희망 장학재단 장학생 선발 시스템 — Vercel Flask REST API
후원사: 삼양 | 수여식: 2026년 4월 30일
이사장: 전동진 | 사무국장: 임재영
"""

import io
import json
import os
import re
import math
import zipfile
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader
from flask import Flask, jsonify, request

# ──────────────────────────────────────────────────────────────────────
# 프론트엔드 HTML — 파일 시스템 의존 없이 직접 내장
# (Vercel 서버리스 환경에서 includeFiles가 불안정하므로 임베드 방식 사용)
# ──────────────────────────────────────────────────────────────────────
_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>한영자 희망 장학재단 | 장학생 선발 시스템</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <style>
    :root { --navy:#0d1b5e; --navy2:#1a3a8f; }
    body { background:#f5f7fb; font-family:'Segoe UI',sans-serif; }
    .site-header {
      background:linear-gradient(135deg,var(--navy),var(--navy2));
      color:#fff; padding:2rem 1.5rem; text-align:center;
      border-radius:0 0 16px 16px; margin-bottom:1.5rem;
      box-shadow:0 4px 20px rgba(13,27,94,.3);
    }
    .site-header h1 { font-size:2rem; font-weight:900; letter-spacing:2px; margin:0; }
    .site-header p  { margin:.3rem 0 0; opacity:.8; font-size:.9rem; }
    .nav-tabs .nav-link        { color:#555; font-weight:600; }
    .nav-tabs .nav-link.active { color:var(--navy); border-bottom:3px solid var(--navy); }
    .card { border:none; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,.08); }
    .card-header { background:var(--navy); color:#fff; border-radius:12px 12px 0 0 !important; font-weight:700; }
    .metric-card { border-left:5px solid var(--navy); }
    .upload-zone {
      border:2px dashed #aab4cc; border-radius:12px;
      padding:2.5rem; text-align:center; cursor:pointer; transition:background .2s;
    }
    .upload-zone:hover,.upload-zone.dragover { background:#e8ecf8; border-color:var(--navy2); }
    .upload-zone i { font-size:3rem; color:#aab4cc; }
    .table-scroll { overflow-x:auto; max-height:540px; overflow-y:auto; }
    .table thead { position:sticky; top:0; z-index:10; }
    .table thead th { background:var(--navy); color:#fff; white-space:nowrap; }
    .rank-1 { background:rgba(255,215,0,.25) !important; font-weight:700; }
    .rank-2 { background:rgba(192,192,192,.25) !important; font-weight:700; }
    .rank-3 { background:rgba(205,127,50,.25) !important; font-weight:700; }
    .check-mark { color:#198754; font-weight:700; }
    .report-box { background:#eef2ff; border-left:5px solid var(--navy); padding:1.4rem 1.8rem; border-radius:8px; line-height:1.9; }
    #loadingSection { display:none; }
    footer { text-align:center; color:#888; font-size:.82rem; padding:1.5rem 0 2rem; }
    .log-box { background:#1e1e2e; color:#a9b1d6; font-family:monospace; font-size:.78rem; padding:1rem; border-radius:8px; max-height:240px; overflow-y:auto; white-space:pre; }
    .korea-map { position:relative; width:100%; max-width:340px; margin:0 auto; }
    .korea-map svg { width:100%; height:auto; }
    .map-bubble { fill:var(--navy2); fill-opacity:.75; stroke:#fff; stroke-width:1.5; transition:fill-opacity .2s; cursor:default; }
    .map-bubble:hover { fill-opacity:1; }
    .map-label { font-size:9px; fill:#fff; text-anchor:middle; dominant-baseline:middle; pointer-events:none; font-weight:700; }
    .leaderboard-item { display:flex; align-items:center; gap:.6rem; padding:.5rem .8rem; border-bottom:1px solid #eee; }
    .leaderboard-item:last-child { border-bottom:none; }
    .lb-rank { min-width:28px; font-weight:800; font-size:1rem; color:var(--navy); }
    .lb-name { flex-grow:1; font-weight:600; }
    .lb-score { background:var(--navy); color:#fff; border-radius:20px; padding:2px 10px; font-size:.82rem; font-weight:700; }
    .lb-region { font-size:.78rem; color:#666; }
  </style>
</head>
<body>
<div class="site-header">
  <h1>🎓 한영자 희망 장학재단</h1>
  <p>장학생 자동 선발 시스템 &nbsp;|&nbsp; 후원사: 삼양</p>
  <p style="font-size:.8rem;opacity:.65;">수여식: 2026년 4월 30일 &nbsp;·&nbsp; 이사장: 전동진 &nbsp;·&nbsp; 사무국장: 임재영</p>
</div>

<div class="container-fluid px-4" style="max-width:1280px;">
  <div id="alertBox"></div>

  <ul class="nav nav-tabs mb-3" id="mainTab">
    <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#tabUpload"><i class="bi bi-upload"></i> 서류 업로드</a></li>
    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#tabResult"><i class="bi bi-trophy"></i> 선발 결과</a></li>
    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#tabStats"><i class="bi bi-bar-chart-line"></i> 통계 리포트</a></li>
    <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#tabDash"><i class="bi bi-map"></i> 지역 대시보드</a></li>
  </ul>

  <div class="tab-content">

    <!-- 탭1: 업로드 -->
    <div class="tab-pane fade show active" id="tabUpload">
      <div class="row g-3">
        <div class="col-lg-7">
          <div class="card">
            <div class="card-header"><i class="bi bi-folder-plus"></i> 서류 ZIP 업로드</div>
            <div class="card-body">
              <p class="text-muted small mb-3">신청자별 폴더에 <strong>4종 서류</strong>(자립지원 대상자 확인서, 재학증명서, 성적증명서, 가산점 서류)가 담긴 ZIP 파일을 업로드하세요.</p>
              <div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()">
                <i class="bi bi-file-earmark-zip"></i>
                <p class="mt-2 mb-0 fw-semibold">여기를 클릭하거나 ZIP 파일을 드래그 앤 드롭</p>
                <p class="text-muted small">최대 50MB</p>
              </div>
              <input type="file" id="fileInput" accept=".zip" class="d-none" onchange="onFileSelect(this)" />
              <div id="fileInfo" class="mt-2 small text-success d-none"></div>
              <div class="d-flex gap-2 mt-3">
                <button class="btn btn-primary flex-grow-1" id="uploadBtn" onclick="uploadFile()" disabled><i class="bi bi-search"></i> 분석 시작</button>
                <button class="btn btn-outline-secondary flex-grow-1" onclick="runDemo()"><i class="bi bi-flask"></i> 데모 테스트</button>
              </div>
            </div>
          </div>
        </div>
        <div class="col-lg-5">
          <div class="card h-100">
            <div class="card-header"><i class="bi bi-info-circle"></i> 선발 기준 안내</div>
            <div class="card-body small">
              <table class="table table-sm table-bordered mb-2">
                <thead class="table-light"><tr><th>항목</th><th>배점</th></tr></thead>
                <tbody>
                  <tr><td>학년 점수</td><td>최대 50점</td></tr>
                  <tr><td>학업 이수율</td><td>최대 50점</td></tr>
                  <tr><td>가산점</td><td>최대 5점</td></tr>
                </tbody>
              </table>
              <p class="fw-semibold mb-1">학년 점수 <span class="badge bg-success" style="font-size:.72rem">2·3·4년제 정규화</span></p>
              <ul class="mb-2">
                <li style="font-size:.82rem"><strong>(현재 학년 ÷ 학제 총 학년) × 50점</strong></li>
                <li style="font-size:.82rem">4년제 4학년·3년제 3학년·2년제 2학년 → 모두 <strong>50점</strong></li>
              </ul>
              <p class="fw-semibold mb-1">가산점 세부</p>
              <ul class="mb-2">
                <li>국가자격증/어학 → <span class="text-success fw-bold">+3</span></li>
                <li>봉사 50h 이상 → <span class="text-success fw-bold">+2</span></li>
              </ul>
              <div class="alert alert-warning py-2 mb-0 small"><i class="bi bi-shield-lock"></i> 주민번호 등 민감 정보는 추출 즉시 마스킹됩니다.</div>
            </div>
          </div>
        </div>
        <div class="col-12">
          <div class="d-flex align-items-center gap-2 p-2 border rounded bg-white">
            <div class="flex-grow-1" id="excludeStatus"></div>
            <button class="btn btn-outline-danger btn-sm d-none" id="excludeClearBtn" onclick="clearExcluded()"><i class="bi bi-x-circle"></i> 초기화</button>
          </div>
        </div>
        <div class="col-12">
          <div class="card">
            <div class="card-header"><i class="bi bi-folder-symlink"></i> ZIP 파일 구조 예시</div>
            <div class="card-body">
              <pre class="mb-0 small bg-light p-3 rounded">📦 신청서류.zip
├── 홍길동/
│   ├── 자립지원대상자확인서.pdf
│   ├── 재학증명서.pdf
│   ├── 성적증명서.pdf
│   └── 가산점서류.pdf
└── 김철수/ ...</pre>
              <p class="mt-2 mb-0 text-muted small">※ <strong>자립지원 대상자 확인서</strong>가 없는 신청자는 자동으로 선발 대상에서 제외됩니다.</p>
            </div>
          </div>
        </div>
      </div>

      <div id="loadingSection" class="text-center py-5">
        <div class="spinner-border text-primary" style="width:3rem;height:3rem;"></div>
        <p class="mt-3 fw-semibold text-secondary" id="loadingText">서류를 분석하고 있습니다...</p>
      </div>

      <div class="mt-3 d-none" id="logSection">
        <div class="accordion">
          <div class="accordion-item">
            <h2 class="accordion-header">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#logCollapse">
                <i class="bi bi-journal-text me-2"></i> 처리 로그 (투명성 원칙에 따른 처리 이력)
              </button>
            </h2>
            <div id="logCollapse" class="accordion-collapse collapse">
              <div class="accordion-body p-0"><div class="log-box" id="logContent"></div></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 탭2: 선발 결과 -->
    <div class="tab-pane fade" id="tabResult">
      <div id="resultEmpty" class="text-center text-muted py-5">
        <i class="bi bi-arrow-left-circle" style="font-size:2rem;"></i>
        <p class="mt-2">'서류 업로드' 탭에서 분석을 먼저 실행하세요.</p>
      </div>
      <div id="resultContent" class="d-none">
        <div class="alert alert-success d-flex align-items-start mb-3">
          <i class="bi bi-trophy-fill me-2 mt-1" style="font-size:1.3rem;"></i>
          <div>
            <strong>2026년도 한영자 희망 장학재단 장학생 최종 선발 명단</strong>
            <div class="small text-muted mt-1" id="resultMeta"></div>
          </div>
        </div>
        <div class="row g-2 mb-3" id="resultMetrics"></div>
        <div class="d-flex gap-2 mb-3 flex-wrap">
          <button class="btn btn-success btn-sm" onclick="downloadCSV('selected')"><i class="bi bi-download"></i> 선발 명단 CSV</button>
          <button class="btn btn-outline-secondary btn-sm" onclick="downloadCSV('all')"><i class="bi bi-download"></i> 전체 자격자 CSV</button>
          <button class="btn btn-dark btn-sm ms-auto" onclick="generateReport()" style="background:linear-gradient(135deg,#0d1b5e,#1a3a8f);border:none;letter-spacing:.5px;"><i class="bi bi-file-earmark-richtext"></i>&nbsp; 이사회 보고서 생성</button>
        </div>
        <div class="card mb-3">
          <div class="card-header"><i class="bi bi-table"></i> 최종 선발 명단</div>
          <div class="card-body p-0">
            <div class="table-scroll">
              <table class="table table-hover table-sm mb-0">
                <thead><tr><th>순위</th><th>성명</th><th>학제</th><th>학년</th><th>전공</th><th>이수학점</th><th>졸업기준</th><th>이수율(%)</th><th>GPA</th><th>학년점수</th><th>이수율점수</th><th>가산점</th><th>총점</th><th>자격증</th><th>봉사</th></tr></thead>
                <tbody id="resultTbody"></tbody>
              </table>
            </div>
          </div>
        </div>
        <div id="warningSection" class="d-none">
          <div class="accordion">
            <div class="accordion-item border-warning">
              <h2 class="accordion-header">
                <button class="accordion-button collapsed bg-warning bg-opacity-10" type="button" data-bs-toggle="collapse" data-bs-target="#warnCollapse">
                  <i class="bi bi-exclamation-triangle me-2 text-warning"></i><span id="warnCount"></span>
                </button>
              </h2>
              <div id="warnCollapse" class="accordion-collapse collapse">
                <div class="accordion-body p-0">
                  <table class="table table-sm mb-0"><thead><tr><th>성명</th><th>주의사항</th></tr></thead><tbody id="warnTbody"></tbody></table>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 탭3: 통계 -->
    <div class="tab-pane fade" id="tabStats">
      <div id="statsEmpty" class="text-center text-muted py-5">
        <i class="bi bi-arrow-left-circle" style="font-size:2rem;"></i>
        <p class="mt-2">'서류 업로드' 탭에서 분석을 먼저 실행하세요.</p>
      </div>
      <div id="statsContent" class="d-none">
        <div class="row g-2 mb-3" id="statsMetrics"></div>
        <div class="row g-3 mb-3">
          <div class="col-md-6"><div class="card"><div class="card-header"><i class="bi bi-bar-chart"></i> 학년별 선발 인원</div><div class="card-body"><canvas id="gradeChart" height="220"></canvas></div></div></div>
          <div class="col-md-6"><div class="card"><div class="card-header"><i class="bi bi-graph-up"></i> 선발자 점수 분포</div><div class="card-body"><canvas id="scoreChart" height="220"></canvas></div></div></div>
        </div>
        <div class="row g-2 mb-3" id="bonusMetrics"></div>
        <div class="card">
          <div class="card-header"><i class="bi bi-file-earmark-text"></i> 선발 취지 보고서</div>
          <div class="card-body"><div class="report-box" id="reportBox"></div></div>
        </div>
      </div>
    </div>

    <!-- 탭4: 지역 대시보드 -->
    <div class="tab-pane fade" id="tabDash">
      <div id="dashEmpty" class="text-center text-muted py-5">
        <i class="bi bi-arrow-left-circle" style="font-size:2rem;"></i>
        <p class="mt-2">'서류 업로드' 탭에서 분석을 먼저 실행하세요.</p>
      </div>
      <div id="dashContent" class="d-none">
        <div class="row g-2 mb-3" id="dashMetrics"></div>
        <div class="row g-3">
          <!-- 지도 버블 맵 -->
          <div class="col-lg-4">
            <div class="card h-100">
              <div class="card-header"><i class="bi bi-geo-alt"></i> 지역별 분포 (거주지 기준)</div>
              <div class="card-body d-flex align-items-center justify-content-center">
                <div class="korea-map">
                  <svg id="koreaSvg" viewBox="0 0 400 500" xmlns="http://www.w3.org/2000/svg">
                    <!-- 한반도 배경 실루엣 (간략화) -->
                    <rect width="400" height="500" fill="#f0f4ff" rx="8"/>
                    <text x="200" y="20" text-anchor="middle" font-size="11" fill="#aab4cc" font-weight="600">대한민국 선발자 분포</text>
                    <g id="mapBubbles"></g>
                  </svg>
                </div>
              </div>
            </div>
          </div>
          <!-- 지역별 수평 막대 차트 -->
          <div class="col-lg-4">
            <div class="card h-100">
              <div class="card-header"><i class="bi bi-bar-chart-steps"></i> 지역별 선발 인원</div>
              <div class="card-body">
                <canvas id="regionChart" style="max-height:380px;"></canvas>
              </div>
            </div>
          </div>
          <!-- 점수 리더보드 -->
          <div class="col-lg-4">
            <div class="card h-100">
              <div class="card-header"><i class="bi bi-list-ol"></i> 선발 순위 (상위 10명)</div>
              <div class="card-body p-0" id="leaderboardList" style="overflow-y:auto;max-height:420px;"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</div>

<footer>
  한영자 희망 장학재단 장학생 선발 시스템 &nbsp;|&nbsp; 이사장 전동진 印 &nbsp;·&nbsp; 사무국장 임재영 印<br>
  본 시스템은 「개인정보보호법」에 따라 주민등록번호 등 민감 정보를 마스킹 처리합니다.
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
let G = { selected:[], all:[], stats:null, warnings:[], log:'' };
let gradeChart=null, scoreChart=null, regionChart=null;

function onFileSelect(input) {
  const f = input.files[0]; if(!f) return;
  const el = document.getElementById('fileInfo');
  el.textContent = '✅ ' + f.name + '  (' + (f.size/1024).toFixed(1) + ' KB)';
  el.classList.remove('d-none');
  document.getElementById('uploadBtn').disabled = false;
}

const zone = document.getElementById('uploadZone');
zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('dragover'); });
zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
zone.addEventListener('drop', e => {
  e.preventDefault(); zone.classList.remove('dragover');
  const dt = new DataTransfer(); dt.items.add(e.dataTransfer.files[0]);
  const fi = document.getElementById('fileInput'); fi.files = dt.files; onFileSelect(fi);
});

async function uploadFile() {
  const f = document.getElementById('fileInput').files[0]; if(!f) return;
  const fd = new FormData(); fd.append('file', f);
  await callAPI('/api/upload', fd);
}
async function runDemo() { await callAPI('/api/demo', new FormData(), '데모 데이터로 분석 중...'); }

async function callAPI(url, body, msg='서류를 분석하고 있습니다...') {
  if(url==='/api/upload') { body.append('excluded_names', JSON.stringify([...loadExcluded()])); }
  setLoading(true, msg); clearAlert();
  try {
    const res  = await fetch(url, {method:'POST', body});
    const data = await res.json();
    if(!data.success) throw new Error(data.error || '알 수 없는 오류');
    applyData(data);
    showAlert('success', '🎉 분석 완료! 총 <strong>' + data.total_applicants + '명</strong> 중 <strong>' + data.selected_count + '명</strong> 최종 선발' + (data.is_demo?' <span class="badge bg-warning text-dark">데모</span>':''));
    new bootstrap.Tab(document.querySelector('[href="#tabResult"]')).show();
  } catch(e) { showAlert('danger','❌ '+e.message); }
  finally { setLoading(false); }
}

function applyData(data) {
  G.selected=data.results||[]; G.all=data.all_results||[];
  G.stats=data.stats||{}; G.warnings=data.warnings||[]; G.log=data.log||'';
  if(!data.is_demo && G.selected.length>0) addToExcluded(G.selected.map(r=>r['성명']));
  renderResult(data); renderStats(data.stats); renderDashboard(data);
  if(G.log){ document.getElementById('logContent').textContent=G.log; document.getElementById('logSection').classList.remove('d-none'); }
}

function renderResult(data) {
  document.getElementById('resultEmpty').classList.add('d-none');
  document.getElementById('resultContent').classList.remove('d-none');
  const now = new Date();
  document.getElementById('resultMeta').innerHTML = '선발 기준일: '+now.toLocaleDateString('ko-KR')+' &nbsp;|&nbsp; 수여식: 2026년 4월 30일 &nbsp;|&nbsp; 이사장 전동진 印 &nbsp;|&nbsp; 사무국장 임재영 印';
  document.getElementById('resultMetrics').innerHTML = mkMetrics([
    {label:'총 신청자', value:data.total_applicants+'명', icon:'people'},
    {label:'자격 충족', value:data.eligible_count+'명',   icon:'person-check'},
    {label:'최종 선발', value:data.selected_count+'명',   icon:'trophy', color:'text-success'},
  ]);
  const tb = document.getElementById('resultTbody'); tb.innerHTML='';
  G.selected.forEach(r => {
    const cls = r['순위']===1?'rank-1':r['순위']===2?'rank-2':r['순위']===3?'rank-3':'';
    tb.insertAdjacentHTML('beforeend','<tr class="'+cls+'"><td><strong>'+r['순위']+'</strong></td><td>'+esc(r['성명'])+'</td><td class="text-center"><span class="badge bg-secondary">'+esc(r['학제']||'4년제')+'</span></td><td>'+esc(r['학년'])+'</td><td class="text-nowrap">'+esc(r['전공'])+'</td><td>'+r['이수학점']+'</td><td>'+r['졸업기준학점']+'</td><td><strong>'+r['이수율']+'%</strong></td><td>'+r['GPA']+'</td><td>'+r['학년점수']+'</td><td>'+r['이수율점수']+'</td><td>'+r['가산점']+'</td><td><strong>'+r['총점']+'</strong></td><td class="check-mark text-center">'+(r['자격증어학']||'')+'</td><td class="check-mark text-center">'+(r['봉사50h']||'')+'</td></tr>');
  });
  if(G.warnings.length>0){
    document.getElementById('warningSection').classList.remove('d-none');
    document.getElementById('warnCount').textContent='파싱 주의사항 ('+G.warnings.length+'건)';
    const wb=document.getElementById('warnTbody'); wb.innerHTML='';
    G.warnings.forEach(w=>wb.insertAdjacentHTML('beforeend','<tr><td>'+esc(w.name)+'</td><td class="small">'+esc(w.note)+'</td></tr>'));
  }
}

function renderStats(stats) {
  if(!stats) return;
  document.getElementById('statsEmpty').classList.add('d-none');
  document.getElementById('statsContent').classList.remove('d-none');
  document.getElementById('statsMetrics').innerHTML = mkMetrics([
    {label:'총 신청자',   value:stats.total_applicants+'명', icon:'people'},
    {label:'최종 선발',   value:stats.selected_count+'명',   icon:'trophy', color:'text-success'},
    {label:'선발률',      value:stats.selection_rate+'%',    icon:'percent'},
    {label:'평균 점수',   value:stats.avg_score+'점',        icon:'star'},
    {label:'평균 이수율', value:stats.avg_completion+'%',    icon:'journal-check'},
  ]);
  document.getElementById('bonusMetrics').innerHTML = mkMetrics([
    {label:'자격증/어학 성적', value:stats.cert_count+'명', icon:'award'},
    {label:'봉사 50h 이상',    value:stats.vol_count+'명',  icon:'heart'},
  ]);
  const gl=Object.keys(stats.grade_dist).sort().reverse();
  mkChart('gradeChart', gl, gl.map(k=>stats.grade_dist[k]), '선발 인원','#1a3a8f', c=>gradeChart=c, gradeChart);
  const sl=G.selected.map((_,i)=>(i+1)+'위'), sd=G.selected.map(r=>r['총점']);
  mkChart('scoreChart', sl, sd, '총점','#2e7d32', c=>scoreChart=c, scoreChart);
  document.getElementById('reportBox').innerHTML =
    '<strong>한영자 희망 장학재단 2026년도 장학생 선발 결과 보고</strong><br><br>' +
    '본 재단은 <strong>자립준비청년의 실질적 자립 지원</strong>을 목적으로, 자립지원 대상자 <strong>'+stats.total_applicants+'명</strong>의 지원서를 심사하였습니다.<br><br>' +
    '학년 점수, 학업 이수율, 사회적 역량을 종합하여 <strong>'+stats.selected_count+'명</strong>을 최종 선발하였으며, 평균 점수는 <strong>'+stats.avg_score+'점</strong> (최고 '+stats.max_score+'점 / 최저 '+stats.min_score+'점), 평균 이수율은 <strong>'+stats.avg_completion+'%</strong>입니다.<br><br>' +
    '국가자격증·어학성적 보유자 <strong>'+stats.cert_count+'명</strong>, 봉사 50시간 이상 달성자 <strong>'+stats.vol_count+'명</strong>에게 가산점이 부여되었습니다. 수여식은 <strong>2026년 4월 30일</strong>입니다.<br><br>' +
    '<em>이사장 전동진 &nbsp;印 &nbsp;&nbsp; 사무국장 임재영 &nbsp;印</em>';
}

function mkChart(id, labels, data, label, color, setter, old) {
  if(old) old.destroy();
  setter(new Chart(document.getElementById(id).getContext('2d'),{type:'bar',data:{labels,datasets:[{label,data,backgroundColor:color+'cc',borderColor:color,borderWidth:1}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{stepSize:1}}}}}));
}

function downloadCSV(type) {
  const rows = type==='selected'?G.selected:G.all;
  if(!rows||!rows.length) return;
  const excl=new Set(['_학년숫자','_이수율정렬']);
  const hdr=Object.keys(rows[0]).filter(k=>!excl.has(k));
  const lines=[hdr.join(','),...rows.map(r=>hdr.map(h=>{const v=r[h]??''; return /[,"\n]/.test(String(v))?'"'+String(v).replace(/"/g,'""')+'"':v;}).join(','))];
  const blob=new Blob(['\uFEFF'+lines.join('\n')],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=url; a.download=(type==='selected'?'한영자 희망 장학재단_선발명단_':'한영자 희망 장학재단_전체명단_')+new Date().toISOString().slice(0,10).replace(/-/g,'')+'.csv';
  a.click(); URL.revokeObjectURL(url);
}

function mkMetrics(items){return items.map(m=>'<div class="col-sm-6 col-lg-auto flex-grow-1"><div class="card metric-card p-3 h-100"><div class="text-muted small"><i class="bi bi-'+m.icon+' me-1"></i>'+m.label+'</div><div class="fs-3 fw-bold mt-1 '+(m.color||'text-dark')+'">'+m.value+'</div></div></div>').join('');}
function setLoading(on,msg=''){document.getElementById('loadingSection').style.display=on?'block':'none';document.getElementById('loadingText').textContent=msg;document.getElementById('uploadBtn').disabled=on;}
function showAlert(type,html){document.getElementById('alertBox').innerHTML='<div class="alert alert-'+type+' alert-dismissible fade show" role="alert">'+html+'<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>';}
function clearAlert(){document.getElementById('alertBox').innerHTML='';}
function esc(s){return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// ── 이사회 보고서 생성 ──
function generateReport() {
  if (!G.selected || !G.selected.length) { showAlert('warning','선발 결과가 없습니다. 먼저 분석을 실행하세요.'); return; }
  const now = new Date();
  const dateStr = now.toLocaleDateString('ko-KR',{year:'numeric',month:'long',day:'numeric'});
  const st = G.stats||{};
  const gdRows = Object.entries(st.grade_dist||{}).sort((a,b)=>b[0].localeCompare(a[0]))
    .map(([g,c])=>`<tr><td>${g}</td><td style="text-align:center">${c}명</td><td style="text-align:center">${(st.selected_count?Math.round(c/st.selected_count*100):0)}%</td></tr>`).join('');
  const rdRows = Object.entries(st.region_dist||{}).filter(([k])=>k!=='미확인').sort((a,b)=>b[1]-a[1]).slice(0,8)
    .map(([r,c])=>`<tr><td>${r}</td><td style="text-align:center">${c}명</td><td style="text-align:center">${(st.selected_count?Math.round(c/st.selected_count*100):0)}%</td></tr>`).join('');
  const schRows = G.selected.map(r=>`<tr>
    <td style="text-align:center;font-weight:700;color:#0d1b5e">${r['순위']}</td>
    <td style="text-align:center;font-weight:700">${esc(r['성명'])}</td>
    <td style="text-align:center;font-size:11px">${esc(r['학제']||'4년제')}</td>
    <td style="text-align:center">${esc(r['지역']||'미확인')}</td>
    <td style="font-size:11px">${esc(r['전공'])}</td>
    <td style="text-align:center">${esc(r['학년'])}</td>
    <td style="text-align:center">${r['GPA']}</td>
    <td style="text-align:center">${r['이수율']}%</td>
    <td style="text-align:center;font-weight:800;color:#0d1b5e">${r['총점']}</td>
    <td style="text-align:center;color:#1a6b3a">${r['자격증어학']?'●':''}</td>
    <td style="text-align:center;color:#1a6b3a">${r['봉사50h']?'●':''}</td>
  </tr>`).join('');

  const html=`<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>한영자 희망 장학재단 — 이사회 보고서 2026</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;700;900&family=Noto+Sans+KR:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Noto Sans KR','Malgun Gothic',sans-serif;background:#e8e0d0;color:#1a1a2e;padding:28px 16px;}
.print-bar{background:#0d1b5e;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;max-width:880px;margin:0 auto 18px;border-radius:6px;}
.print-bar span{color:#c8b97a;font-size:13px;font-weight:600;}
.print-bar button{background:#c8b97a;border:none;color:#0d1b5e;font-weight:800;padding:8px 24px;border-radius:4px;cursor:pointer;font-size:13px;letter-spacing:.5px;}
.print-bar button:hover{background:#d4c88a;}
.page{background:#fff;max-width:880px;margin:0 auto;padding:64px 72px 72px;box-shadow:0 12px 48px rgba(0,0,0,.22);position:relative;overflow:hidden;}
.page::before{content:'한영자 희망 장학재단';position:absolute;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-30deg);font-size:80px;color:rgba(13,27,94,.03);font-weight:900;white-space:nowrap;pointer-events:none;z-index:0;font-family:'Noto Serif KR',serif;}
.top-stripe{position:absolute;top:0;left:0;right:0;height:7px;background:linear-gradient(90deg,#0d1b5e 60%,#c8b97a 100%);}
.doc-header{text-align:center;padding-bottom:28px;border-bottom:2px solid #0d1b5e;margin-bottom:28px;position:relative;}
.emblem{width:68px;height:68px;border:3px solid #0d1b5e;border-radius:50%;margin:0 auto 10px;display:flex;align-items:center;justify-content:center;font-size:28px;background:#f5f8ff;}
.doc-header h1{font-family:'Noto Serif KR',serif;font-size:24px;font-weight:900;color:#0d1b5e;letter-spacing:4px;margin-bottom:4px;}
.doc-header h2{font-family:'Noto Serif KR',serif;font-size:17px;font-weight:700;color:#222;letter-spacing:2px;margin-bottom:20px;}
.gold-line{width:80px;height:2px;background:#c8b97a;margin:10px auto;}
.doc-meta{display:flex;justify-content:center;gap:36px;font-size:13px;color:#444;}
.doc-meta strong{color:#0d1b5e;}
.info-box{border:1px solid #c8b97a;border-radius:4px;background:linear-gradient(to bottom,#fdfaf0,#faf6e8);margin-bottom:30px;}
.info-box table{width:100%;border-collapse:collapse;}
.info-box td{padding:8px 16px;font-size:13px;border-bottom:1px solid #ede5c8;vertical-align:top;}
.info-box td:first-child{width:110px;background:rgba(200,185,122,.18);font-weight:700;color:#5c4a1e;border-right:1px solid #ede5c8;}
.info-box tr:last-child td{border-bottom:none;}
.sec{display:flex;align-items:center;gap:10px;font-family:'Noto Serif KR',serif;font-size:14.5px;font-weight:900;color:#fff;background:linear-gradient(90deg,#0d1b5e,#1a3a8f 80%);padding:9px 18px;border-radius:4px;margin:28px 0 14px;letter-spacing:1px;}
.sec-num{font-size:16px;font-weight:900;border-right:1px solid rgba(255,255,255,.35);padding-right:10px;margin-right:2px;}
.notice{background:#f8f9ff;border:1px solid #d0d8f0;border-left:4px solid #0d1b5e;padding:13px 16px;font-size:12.5px;color:#444;border-radius:0 4px 4px 0;line-height:1.9;margin-bottom:14px;}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;}
.stat-card{text-align:center;border:1px solid #d0d8f0;border-radius:6px;padding:14px 8px;background:#f8f9ff;transition:transform .15s;}
.stat-card .val{font-size:21px;font-weight:900;color:#0d1b5e;font-family:'Noto Serif KR',serif;}
.stat-card .lbl{font-size:11px;color:#666;margin-top:3px;}
table.doc-table{width:100%;border-collapse:collapse;font-size:12px;}
table.doc-table thead th{background:#0d1b5e;color:#fff;padding:8px 5px;text-align:center;font-weight:600;white-space:nowrap;}
table.doc-table tbody td{padding:7px 5px;border-bottom:1px solid #eee;vertical-align:middle;}
table.doc-table tbody tr:nth-child(even){background:#f9faff;}
table.doc-table tbody tr:first-child td{background:rgba(255,215,0,.18)!important;font-weight:700;}
table.doc-table tbody tr:nth-child(2) td{background:rgba(192,192,192,.18)!important;font-weight:700;}
table.doc-table tbody tr:nth-child(3) td{background:rgba(205,127,50,.15)!important;font-weight:700;}
table.sub-table{border-collapse:collapse;font-size:13px;}
table.sub-table th{background:#1a3a8f;color:#fff;padding:7px 14px;text-align:center;}
table.sub-table td{padding:7px 14px;border-bottom:1px solid #e8e8e8;text-align:center;}
.sig-section{margin-top:54px;padding-top:22px;border-top:2px solid #0d1b5e;}
.sig-intro{font-family:'Noto Serif KR',serif;font-size:13.5px;color:#333;text-align:center;margin-bottom:28px;line-height:1.8;}
.sig-grid{display:flex;justify-content:space-around;align-items:flex-end;flex-wrap:wrap;gap:20px;}
.sig-block{text-align:center;}
.sig-block .role{font-size:12px;color:#666;font-weight:600;margin-bottom:4px;letter-spacing:1px;}
.sig-block .name{font-family:'Noto Serif KR',serif;font-size:20px;font-weight:900;color:#0d1b5e;letter-spacing:4px;margin-bottom:6px;}
.stamp{display:inline-flex;width:72px;height:72px;border:2.5px solid #b03030;border-radius:50%;color:#b03030;font-size:10.5px;font-weight:900;line-height:1.4;padding:10px 4px;text-align:center;align-items:center;justify-content:center;transform:rotate(-13deg);opacity:.82;margin-top:4px;font-family:'Noto Serif KR',serif;flex-direction:column;}
.doc-footer{margin-top:36px;padding-top:14px;border-top:1px solid #ddd;display:flex;justify-content:space-between;font-size:11px;color:#999;}
@media print{body{background:#fff;padding:0;}
.page{box-shadow:none;padding:40px 50px;}
.print-bar{display:none;}
table.doc-table{font-size:10.5px;}
.stats-grid{grid-template-columns:repeat(4,1fr);}}
</style></head><body>
<div class="print-bar">
  <span>📋 한영자 희망 장학재단 &nbsp;|&nbsp; 2026년도 장학생 최종 선발 결과 보고서</span>
  <button onclick="window.print()">🖨&nbsp; 인쇄 · PDF 저장</button>
</div>
<div class="page">
  <div class="top-stripe"></div>
  <div class="doc-header">
    <div class="emblem">🎓</div>
    <h1>한영자 희망 장학재단</h1>
    <div class="gold-line"></div>
    <h2>2026년도 장학생 최종 선발 결과 보고</h2>
    <div class="doc-meta">
      <span>보고 일자: <strong>${dateStr}</strong></span>
      <span>보고 대상: <strong>이 사 회</strong></span>
      <span>기 안: <strong>사무국장 임재영</strong></span>
    </div>
  </div>
  <div class="info-box"><table>
    <tr><td>문서 구분</td><td>이사회 보고용 내부 문서 &nbsp;<span style="background:#0d1b5e;color:#fff;font-size:10px;padding:1px 7px;border-radius:3px;font-weight:700">대내용</span></td></tr>
    <tr><td>후 원 사</td><td><strong>삼양</strong></td></tr>
    <tr><td>수여식 일자</td><td>2026년 4월 30일</td></tr>
    <tr><td>보고 내용</td><td>2026년도 한영자 희망 장학재단 장학생 선발 심사 결과 및 최종 명단</td></tr>
  </table></div>

  <div class="sec"><span class="sec-num">Ⅰ</span>선발 개요</div>
  <div class="notice">
    본 재단은 아동양육시설·공동생활가정 등 보호 종료 청년(자립준비청년)의 고등교육 기회 보장 및 실질적 자립 역량 강화를 목적으로,
    「자립지원 대상자 확인서」 제출자를 대상으로 2026년도 장학생 선발을 실시하였습니다.<br>
    본 선발 과정은 전산화된 자동 채점 시스템을 통해 객관적 기준에 따라 공정하게 진행되었으며,
    주민등록번호 등 민감 정보는 「개인정보보호법」에 따라 추출 즉시 마스킹 처리하였습니다.
  </div>

  <div class="sec"><span class="sec-num">Ⅱ</span>선발 기준</div>
  <table class="sub-table" style="width:100%;margin-bottom:8px">
    <thead><tr><th style="width:28%;text-align:left">평가 항목</th><th style="width:18%">배점</th><th style="text-align:left">세부 기준</th></tr></thead>
    <tbody>
      <tr><td style="text-align:left;font-weight:600">학년 점수</td><td>최대 50점</td><td style="text-align:left">(현재 학년 ÷ 학제 총 학년) × 50점 &nbsp;<span style="background:#1a6b3a;color:#fff;font-size:10px;padding:1px 6px;border-radius:3px">2·3·4년제 공평 정규화</span></td></tr>
      <tr><td style="text-align:left;font-weight:600">학업 이수율</td><td>최대 50점</td><td style="text-align:left">취득학점 ÷ 졸업기준학점 × 50점</td></tr>
      <tr><td style="text-align:left;font-weight:600">가산점</td><td>최대 5점</td><td style="text-align:left">국가자격증·어학성적 +3점 &nbsp;·&nbsp; 봉사 50시간 이상 +2점</td></tr>
      <tr style="background:#f0f4ff"><td style="text-align:left;font-weight:800">합 계</td><td style="font-weight:800">최대 105점</td><td style="text-align:left;font-size:12px">총점 기준 내림차순 선발 (동점 시: 이수율 → 학년 → GPA 순)</td></tr>
    </tbody>
  </table>
  <p style="font-size:12px;color:#888;margin-bottom:0">※ 「자립지원 대상자 확인서」 미제출자는 자격 심사 이전에 자동 제외됩니다.</p>

  <div class="sec"><span class="sec-num">Ⅲ</span>선발 결과 통계</div>
  <div class="stats-grid">
    <div class="stat-card"><div class="val">${st.total_applicants||0}명</div><div class="lbl">총 신청자</div></div>
    <div class="stat-card"><div class="val">${st.selected_count||0}명</div><div class="lbl">최종 선발</div></div>
    <div class="stat-card"><div class="val">${st.selection_rate||0}%</div><div class="lbl">선발률</div></div>
    <div class="stat-card"><div class="val">${st.avg_score||0}점</div><div class="lbl">평균 총점</div></div>
    <div class="stat-card"><div class="val">${st.max_score||0}점</div><div class="lbl">최고 점수</div></div>
    <div class="stat-card"><div class="val">${st.min_score||0}점</div><div class="lbl">최저 점수</div></div>
    <div class="stat-card"><div class="val">${st.avg_completion||0}%</div><div class="lbl">평균 이수율</div></div>
    <div class="stat-card"><div class="val">${st.avg_gpa||0}</div><div class="lbl">평균 GPA</div></div>
  </div>
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px">
    <div><p style="font-size:12.5px;font-weight:700;color:#0d1b5e;margin-bottom:6px">학년별 선발 현황</p>
    <table class="sub-table"><thead><tr><th>학년</th><th>인원</th><th>비율</th></tr></thead><tbody>${gdRows}</tbody></table></div>
    ${rdRows?`<div><p style="font-size:12.5px;font-weight:700;color:#0d1b5e;margin-bottom:6px">지역별 선발 현황 (상위 8개)</p>
    <table class="sub-table"><thead><tr><th>지역</th><th>인원</th><th>비율</th></tr></thead><tbody>${rdRows}</tbody></table></div>`:''}
  </div>
  <div style="display:flex;gap:10px;flex-wrap:wrap">
    <div style="font-size:12.5px;background:#f0f4ff;padding:8px 14px;border-radius:4px;border:1px solid #d0d8f0"><strong>자격증·어학성적 보유</strong>: ${st.cert_count||0}명</div>
    <div style="font-size:12.5px;background:#f0f4ff;padding:8px 14px;border-radius:4px;border:1px solid #d0d8f0"><strong>봉사 50시간 이상</strong>: ${st.vol_count||0}명</div>
  </div>

  <div class="sec"><span class="sec-num">Ⅳ</span>최종 선발자 명단</div>
  <table class="doc-table">
    <thead><tr>
      <th style="width:38px">순위</th><th>성명</th><th>학제</th><th>지역</th><th>전공</th><th>학년</th>
      <th>GPA</th><th>이수율</th><th>총점</th><th title="자격증·어학성적">자격증</th><th title="봉사 50h 이상">봉사</th>
    </tr></thead>
    <tbody>${schRows}</tbody>
  </table>
  <p style="font-size:11px;color:#999;margin-top:6px">※ 자격증 = 국가자격증·어학성적 보유 &nbsp;·&nbsp; 봉사 = 50시간 이상 달성 &nbsp;·&nbsp; ● 해당</p>

  <div class="sig-section">
    <p class="sig-intro">
      위와 같이 2026년도 한영자 희망 장학재단 장학생 최종 선발 결과를 보고드립니다.<br>
      <span style="font-size:12px;color:#888">본 선발은 공정성 원칙에 따라 전산 자동 채점 방식으로 진행되었습니다.</span>
    </p>
    <div class="sig-grid">
      <div class="sig-block">
        <div class="role">사 무 국 장</div>
        <div class="name">임 재 영</div>
        <div class="stamp">한영자<br>희망<br>재단</div>
      </div>
      <div style="text-align:center;font-size:13px;color:#aaa;align-self:center">
        <div style="border:1px solid #ddd;padding:10px 20px;border-radius:4px;background:#fafafa">
          <div style="font-size:11px;color:#bbb;margin-bottom:4px">결재란</div>
          <div style="display:flex;gap:0">
            <div style="border:1px solid #ccc;padding:8px 16px;min-width:60px;text-align:center;font-size:12px">담당<br><br></div>
            <div style="border:1px solid #ccc;border-left:none;padding:8px 16px;min-width:60px;text-align:center;font-size:12px">검토<br><br></div>
            <div style="border:1px solid #ccc;border-left:none;padding:8px 16px;min-width:60px;text-align:center;font-size:12px">승인<br><br></div>
          </div>
        </div>
      </div>
      <div class="sig-block">
        <div class="role">이 사 장</div>
        <div class="name">전 동 진</div>
        <div class="stamp">이사장<br>직 인</div>
      </div>
    </div>
  </div>
  <div class="doc-footer">
    <span>한영자 희망 장학재단 &nbsp;|&nbsp; 후원사: 삼양 &nbsp;|&nbsp; 수여식: 2026년 4월 30일</span>
    <span>본 문서는 「개인정보보호법」에 따라 민감 정보를 마스킹 처리하였습니다.</span>
  </div>
</div></body></html>`;

  const win=window.open('','_blank','width=980,height=820,scrollbars=yes,resizable=yes');
  if(!win){showAlert('warning','팝업이 차단되었습니다. 브라우저 팝업 허용 후 다시 시도하세요.');return;}
  win.document.open(); win.document.write(html); win.document.close();
}

// ── 지역 대시보드 ──
const REGION_POS = {
  '서울':[200,108],'인천':[165,118],'경기':[198,135],
  '강원':[295,100],'충북':[245,168],'충남':[178,185],
  '대전':[210,188],'세종':[205,175],'전북':[193,235],
  '전남':[185,290],'광주':[175,268],'경북':[298,178],
  '대구':[278,210],'경남':[270,265],'울산':[308,238],
  '부산':[292,278],'제주':[188,380],
};

function renderDashboard(data) {
  document.getElementById('dashEmpty').classList.add('d-none');
  document.getElementById('dashContent').classList.remove('d-none');
  const st = data.stats||{};
  document.getElementById('dashMetrics').innerHTML = mkMetrics([
    {label:'총 신청자',   value:(data.total_applicants||0)+'명', icon:'people'},
    {label:'최종 선발',   value:(data.selected_count||0)+'명',   icon:'trophy', color:'text-success'},
    {label:'선발률',      value:(st.selection_rate||0)+'%',      icon:'percent'},
    {label:'평균 총점',   value:(st.avg_score||0)+'점',          icon:'star'},
    {label:'지역 확인',   value:Object.keys(st.region_dist||{}).filter(k=>k!=='미확인').length+'개 지역', icon:'geo-alt'},
  ]);
  drawKoreaMap(st.region_dist||{});
  drawRegionChart(st.region_dist||{});
  drawLeaderboard(G.selected);
}

function drawKoreaMap(rd) {
  const g = document.getElementById('mapBubbles');
  g.innerHTML = '';
  const counts = Object.values(rd).filter(v=>v>0);
  const maxC = counts.length ? Math.max(...counts) : 1;
  Object.entries(REGION_POS).forEach(([name,[cx,cy]])=>{
    const cnt = rd[name]||0;
    const r = cnt>0 ? Math.max(14, Math.min(36, 14 + (cnt/maxC)*22)) : 6;
    const alpha = cnt>0 ? 0.75 : 0.12;
    g.insertAdjacentHTML('beforeend',
      `<circle class="map-bubble" cx="${cx}" cy="${cy}" r="${r}" fill-opacity="${alpha}"/>` +
      `<text class="map-label" x="${cx}" y="${cy}">${name}${cnt>0?'\n'+cnt:''}</text>` +
      (cnt>0?`<text class="map-label" x="${cx}" y="${cy+10}" style="font-size:8px">${cnt}명</text>`:'')
    );
  });
}

function drawRegionChart(rd) {
  const sorted = Object.entries(rd).filter(([,v])=>v>0).sort((a,b)=>b[1]-a[1]);
  const labels = sorted.map(([k])=>k), vals = sorted.map(([,v])=>v);
  if(regionChart) regionChart.destroy();
  if(!labels.length) return;
  regionChart = new Chart(document.getElementById('regionChart').getContext('2d'),{
    type:'bar',
    data:{labels, datasets:[{label:'선발 인원',data:vals,
      backgroundColor:'#1a3a8fcc',borderColor:'#0d1b5e',borderWidth:1}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false}},
      scales:{x:{beginAtZero:true,ticks:{stepSize:1}},y:{ticks:{font:{size:11}}}}}
  });
}

function drawLeaderboard(sel) {
  const lb = document.getElementById('leaderboardList');
  lb.innerHTML = '';
  const medals = ['🥇','🥈','🥉'];
  sel.slice(0,10).forEach((r,i)=>{
    const medal = i<3?medals[i]:''+(i+1)+'.';
    lb.insertAdjacentHTML('beforeend',
      `<div class="leaderboard-item">
        <span class="lb-rank">${medal}</span>
        <span class="lb-name">${esc(r['성명'])}<br><span class="lb-region">${esc(r['지역']||'미확인')} · ${esc(r['학년'])}</span></span>
        <span class="lb-score">${r['총점']}점</span>
      </div>`
    );
  });
}

// ── 이전 선발자 제외 관리 (localStorage 영속화) ──
const _EK='hanyang_excluded';
function loadExcluded(){try{return new Set(JSON.parse(localStorage.getItem(_EK)||'[]'));}catch{return new Set();}}
function saveExcluded(s){localStorage.setItem(_EK,JSON.stringify([...s]));}
function addToExcluded(names){const s=loadExcluded();names.forEach(n=>s.add(n));saveExcluded(s);updateExcludeUI();}
function clearExcluded(){if(!confirm('이전 선발 명단을 초기화하시겠습니까?\n초기화 시 중복 선발 방지가 리셋됩니다.'))return;localStorage.removeItem(_EK);updateExcludeUI();}
function updateExcludeUI(){
  const s=loadExcluded(),el=document.getElementById('excludeStatus'),btn=document.getElementById('excludeClearBtn');
  if(!el)return;
  if(s.size===0){
    el.innerHTML='<i class="bi bi-people"></i> 이전 선발자: <strong>없음</strong> &nbsp;<span class="text-muted">(중복 선발 방지 비활성)</span>';
    el.className='text-secondary small py-1';
  } else {
    el.innerHTML='<i class="bi bi-person-x-fill text-danger"></i> 이전 선발자 <strong>'+s.size+'명</strong>이 이번 선발에서 자동 제외됩니다.';
    el.className='text-warning-emphasis small py-1 fw-semibold';
  }
  if(btn)btn.classList.toggle('d-none',s.size===0);
}
updateExcludeUI();
</script>
</body>
</html>"""

# ──────────────────────────────────────────────────────────────────────
# Flask 앱 설정
# ──────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/api/upload", methods=["OPTIONS"])
@app.route("/api/demo",   methods=["OPTIONS"])
def _preflight():
    return "", 204

@app.route("/")
def serve_index():
    """프론트엔드 HTML 반환 — 파일 시스템 없이 메모리에서 직접 서빙"""
    return _INDEX_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}

# ──────────────────────────────────────────────────────────────────────
# 로깅 (투명성 원칙)
# ──────────────────────────────────────────────────────────────────────
_log_buf = io.StringIO()
_handler = logging.StreamHandler(_log_buf)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logger = logging.getLogger("hanyang_api")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_handler)

def _flush_log() -> str:
    content = _log_buf.getvalue()
    _log_buf.truncate(0); _log_buf.seek(0)
    return content

# ──────────────────────────────────────────────────────────────────────
# 전역 상수
# ──────────────────────────────────────────────────────────────────────
# 학년 점수: (현재학년 ÷ 학제총학년) × 50 — 2·3·4년제 공평 정규화
MAX_SCHOLARS: int = 50
DEFAULT_GRAD_CREDITS: float = 120.0

CERT_KEYWORDS = ["국가기술자격","국가전문자격","기사","산업기사","기능사","기능장","기술사","TOEIC","TOEFL","IELTS","OPIc","JLPT","HSK","토익","토플","오픽","텝스","TEPS","자격증","면허","어학성적"]
VOLUNTEER_KEYWORDS = ["봉사","자원봉사","사회봉사","봉사활동","봉사시간"]
MILITARY_KEYWORDS  = ["병역","현역","예비역","만기전역","군필","복무완료","전역","군복무"]
DOC_ELIGIBILITY_KW = ["자립지원 대상자 확인서","자립지원대상자확인서","자립준비청년 확인서"]
DOC_ENROLLMENT_KW  = ["재학증명서","재학 증명서"]
DOC_TRANSCRIPT_KW  = ["성적증명서","성적표","학업성적","성적 증명서"]
REGION_MAP: Dict[str, List[str]] = {
    "서울":["서울특별시"],"인천":["인천광역시"],"경기":["경기도"],
    "강원":["강원특별자치도","강원도"],"충북":["충청북도"],"충남":["충청남도"],
    "대전":["대전광역시"],"세종":["세종특별자치시","세종시"],
    "전북":["전북특별자치도","전라북도"],"전남":["전라남도"],"광주":["광주광역시"],
    "경북":["경상북도"],"대구":["대구광역시"],"경남":["경상남도"],
    "울산":["울산광역시"],"부산":["부산광역시"],"제주":["제주특별자치도","제주도"],
}

# ──────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ApplicantData:
    applicant_key: str = ""; name: str = "미확인"; grade: int = 0; major: str = ""
    completed_credits: float = 0.0; graduation_credits: float = DEFAULT_GRAD_CREDITS
    gpa: float = 0.0; has_certificate: bool = False; volunteer_hours: float = 0.0
    is_military: bool = False; is_eligible: bool = False; has_enrollment: bool = False
    has_transcript: bool = False; has_bonus_doc: bool = False
    raw_texts: Dict[str, str] = field(default_factory=dict)
    parse_notes: List[str] = field(default_factory=list)
    grade_score: float = 0.0; completion_rate: float = 0.0; completion_score: float = 0.0
    bonus_cert: bool = False; bonus_volunteer: bool = False
    bonus_score: float = 0.0; total_score: float = 0.0; region: str = ""; max_grade: int = 4

# ──────────────────────────────────────────────────────────────────────
# 민감 정보 마스킹
# ──────────────────────────────────────────────────────────────────────
def mask_sensitive(text: str) -> str:
    text = re.sub(r"(\d{6})\s*[-–]\s*(\d{7})", r"\1-*******", text)
    text = re.sub(r"(\d{6})(\d{7})", r"\1*******", text)
    text = re.sub(r"(01\d)\s*[-–]\s*(\d{3,4})\s*[-–]\s*(\d{4})", r"\1-****-\3", text)
    return text

# ──────────────────────────────────────────────────────────────────────
# PDF 파서
# ──────────────────────────────────────────────────────────────────────
class PDFParser:
    @staticmethod
    def extract_text(pdf_bytes: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages  = [page.extract_text() or "" for page in reader.pages]
            return mask_sensitive("\n".join(pages))
        except Exception as e:
            logger.warning(f"PDF 추출 실패: {e}"); return ""

    @staticmethod
    def classify(text: str) -> str:
        if any(k in text for k in DOC_ELIGIBILITY_KW): return "eligibility"
        if any(k in text for k in DOC_ENROLLMENT_KW):  return "enrollment"
        if any(k in text for k in DOC_TRANSCRIPT_KW):  return "transcript"
        if any(k in text for k in CERT_KEYWORDS+VOLUNTEER_KEYWORDS+MILITARY_KEYWORDS): return "bonus"
        return "unknown"

    @staticmethod
    def extract_name(text: str) -> Optional[str]:
        for p in [r"성\s*명\s*[：:]\s*([가-힣]{2,5})",r"이\s*름\s*[：:]\s*([가-힣]{2,5})",r"학생명\s*[：:]\s*([가-힣]{2,5})"]:
            m=re.search(p,text)
            if m: return m.group(1).strip()
        return None

    @staticmethod
    def extract_grade(text: str) -> Optional[int]:
        for p in [r"([1-4])\s*학년",r"학\s*년\s*[：:\s]*([1-4])"]:
            m=re.search(p,text)
            if m:
                g=int(m.group(1))
                if 1<=g<=4: return g
        return None

    @staticmethod
    def extract_major(text: str) -> Optional[str]:
        for p in [r"전\s*공\s*[：:\s]+([^\n\r\t]{2,30})",r"학\s*과\s*[：:\s]+([^\n\r\t]{2,30})",r"학\s*부\s*[：:\s]+([^\n\r\t]{2,30})"]:
            m=re.search(p,text)
            if m:
                v=re.sub(r"\s+"," ",m.group(1)).strip()
                if 2<=len(v)<=40: return v
        return None

    @staticmethod
    def extract_credits(text: str) -> Tuple[Optional[float], Optional[float]]:
        grad=None
        for p in [r"졸업\s*기준\s*학점\s*[：:\s]*(\d+\.?\d*)",r"졸업\s*이수\s*학점\s*[：:\s]*(\d+\.?\d*)",r"졸업\s*학점\s*[：:\s]*(\d+\.?\d*)"]:
            m=re.search(p,text)
            if m: grad=float(m.group(1)); break
        comp=None
        for p in [r"취득\s*학점\s*[：:\s]*(\d+\.?\d*)",r"이수\s*학점\s*[：:\s]*(\d+\.?\d*)",r"누적\s*학점\s*[：:\s]*(\d+\.?\d*)"]:
            m=re.search(p,text)
            if m: comp=float(m.group(1)); break
        return comp, grad

    @staticmethod
    def extract_gpa(text: str) -> Optional[float]:
        for p in [r"전체\s*평점\s*[：:\s]*(\d+\.\d+)",r"누적\s*평점\s*[：:\s]*(\d+\.\d+)",r"평\s*점\s*[：:\s]*(\d+\.\d+)",r"GPA\s*[：:\s]*(\d+\.\d+)"]:
            m=re.search(p,text,re.IGNORECASE)
            if m:
                v=float(m.group(1))
                if 0.0<=v<=4.5: return v
        return None

    @staticmethod
    def check_certificate(text: str) -> bool:
        return any(k.lower() in text.lower() for k in CERT_KEYWORDS)

    @staticmethod
    def extract_volunteer_hours(text: str) -> float:
        for p in [r"봉사\s*시간\s*[：:\s]*(\d+\.?\d*)",r"총\s*봉사\s*[：:\s]*(\d+\.?\d*)\s*시간",r"(\d+\.?\d*)\s*시간"]:
            ms=re.findall(p,text)
            if ms:
                h=max(float(x) for x in ms)
                if 0<h<10000: return h
        return 0.0

    @staticmethod
    def check_military(text: str) -> bool:
        return any(k in text for k in MILITARY_KEYWORDS)

    @staticmethod
    def extract_max_grade(text: str) -> Optional[int]:
        """2·3·4년제 감지 — 4단계 우선순위로 판별"""
        # ① 수업연한 명시 (가장 확실)
        for p in [r"수업\s*연한\s*[：:\s]*([2-4])\s*년",
                  r"([2-4])\s*년\s*제",
                  r"학\s*제\s*[：:\s]*([2-4])\s*년"]:
            m = re.search(p, text)
            if m:
                return int(m.group(1))
        # ② 학교명에 '전문대학' 포함 여부 ('전문대학교'는 4년제이므로 제외)
        if re.search(r"전문대학(?!교)", text):
            if re.search(r"3\s*년\s*제|수업연한\s*[：:\s]*3", text):
                return 3
            return 2
        # ③ 학위 종류 (전문학사 = 2·3년제)
        if "전문학사" in text:
            return 2
        # ④ '대학교' 명시이면 4년제 확정
        if re.search(r"[가-힣]+대학교", text):
            return 4
        return None

    @staticmethod
    def extract_region(text: str) -> Optional[str]:
        for pat in [r"(?:주소|거주지|현주소|주거지)\s*[：:]\s*([^\n\r]{4,80})",
                    r"([가-힣]+(특별시|광역시|특별자치시|특별자치도|도)\b[^\n\r]{0,30})"]:
            m = re.search(pat, text)
            if m:
                addr = m.group(1).strip()
                for region, keywords in REGION_MAP.items():
                    if any(kw in addr for kw in keywords):
                        return region
        return None

# ──────────────────────────────────────────────────────────────────────
# 점수 계산 엔진
# ──────────────────────────────────────────────────────────────────────
class ScoringEngine:
    @staticmethod
    def calculate(a: ApplicantData) -> ApplicantData:
        # 학년 점수: (현재학년 ÷ 학제총학년) × 50 — 2·3·4년제 정규화
        if a.grade > 0 and a.max_grade > 0:
            a.grade_score = round((a.grade / a.max_grade) * 50, 2)
        else:
            a.grade_score = 0.0
        if a.graduation_credits > 0:
            rate = min(a.completed_credits / a.graduation_credits, 1.0)
            a.completion_rate = rate; a.completion_score = round(rate*50, 2)
        bonus = 0
        a.bonus_cert      = a.has_certificate
        a.bonus_volunteer = a.volunteer_hours >= 50.0
        if a.bonus_cert:      bonus += 3
        if a.bonus_volunteer: bonus += 2
        a.bonus_score = float(min(bonus, 5))
        a.total_score = round(a.grade_score + a.completion_score + a.bonus_score, 2)
        return a

# ──────────────────────────────────────────────────────────────────────
# ZIP 처리기
# ──────────────────────────────────────────────────────────────────────
class DocumentProcessor:
    def __init__(self): self._p=PDFParser(); self._s=ScoringEngine()

    def process(self, zip_bytes: bytes) -> List[ApplicantData]:
        applicants: Dict[str, ApplicantData] = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for fp in zf.namelist():
                if not fp.lower().endswith(".pdf") or "__MACOSX" in fp: continue
                key = self._key(fp)
                if key not in applicants: applicants[key]=ApplicantData(applicant_key=key,name=key)
                a = applicants[key]
                try:
                    text = self._p.extract_text(zf.read(fp))
                    if not text.strip(): a.parse_notes.append(f"⚠ '{fp}': 텍스트 추출 불가"); continue
                    dt = self._p.classify(text)
                    a.raw_texts[dt] = a.raw_texts.get(dt,"") + "\n" + text
                    self._apply(a, dt, text)
                except Exception as e:
                    a.parse_notes.append(f"❌ '{fp}': {e}")

        for a in applicants.values():
            for text in a.raw_texts.values():
                name=self._p.extract_name(text)
                if name: a.name=name; break

        results=[]
        for a in applicants.values():
            if not a.is_eligible: a.parse_notes.insert(0,"⛔ 자립지원 대상자 확인서 미확인 — 제외")
            self._s.calculate(a); results.append(a)
        return results

    @staticmethod
    def _key(fp: str) -> str:
        parts=fp.replace("\\","/").split("/")
        if len(parts)>=2: return parts[0].strip()
        base=os.path.splitext(parts[0])[0]
        for sep in ("_","-"," "):
            if sep in base: return base.split(sep)[0].strip()
        return base.strip()

    def _apply(self, a: ApplicantData, dt: str, text: str):
        p=self._p
        if not a.region:
            r=p.extract_region(text)
            if r: a.region=r
        mg=p.extract_max_grade(text)
        if mg and mg!=a.max_grade and mg in (2,3,4): a.max_grade=mg
        if dt=="eligibility": a.is_eligible=True
        elif dt=="enrollment":
            a.has_enrollment=True
            g=p.extract_grade(text); a.grade=g if g else a.grade
            m=p.extract_major(text); a.major=m if m else a.major
        elif dt=="transcript":
            a.has_transcript=True
            comp,grad=p.extract_credits(text)
            if comp is not None: a.completed_credits=comp
            if grad is not None:
                a.graduation_credits=grad
                # 졸업기준학점으로 학제 보조 추론 (키워드 미감지 시 fallback)
                if a.max_grade==4 and grad < 90: a.max_grade=2
                elif a.max_grade==4 and grad < 115: a.max_grade=3
            gpa=p.extract_gpa(text)
            if gpa is not None: a.gpa=gpa
            if a.grade==0:
                g=p.extract_grade(text)
                if g: a.grade=g
            if not a.major:
                m=p.extract_major(text)
                if m: a.major=m
        elif dt=="bonus":
            a.has_bonus_doc=True
            if p.check_certificate(text): a.has_certificate=True
            h=p.extract_volunteer_hours(text)
            if h>0: a.volunteer_hours=max(a.volunteer_hours,h)
            if p.check_military(text): a.is_military=True
        else:
            if any(k in text for k in DOC_ELIGIBILITY_KW): a.is_eligible=True
            if a.grade==0:
                g=p.extract_grade(text)
                if g: a.grade=g
            if not a.major:
                m=p.extract_major(text)
                if m: a.major=m
            comp,grad=p.extract_credits(text)
            if comp and a.completed_credits==0: a.completed_credits=comp
            if grad: a.graduation_credits=grad
            gpa=p.extract_gpa(text)
            if gpa and a.gpa==0: a.gpa=gpa
            if p.check_certificate(text): a.has_certificate=True
            h=p.extract_volunteer_hours(text)
            if h>0: a.volunteer_hours=max(a.volunteer_hours,h)
            if p.check_military(text): a.is_military=True

# ──────────────────────────────────────────────────────────────────────
# 선발 함수
# ──────────────────────────────────────────────────────────────────────
def select_scholars(applicants: List[ApplicantData], n: int=MAX_SCHOLARS, excluded: set=None) -> Tuple[List[Dict],List[Dict]]:
    excluded = excluded or set()
    for a in applicants:
        if a.name in excluded:
            a.parse_notes.insert(0, "⛔ 이전 선발자 — 중복 선발 제외")
    eligible=[a for a in applicants if a.is_eligible and a.name not in excluded]
    if not eligible: return [],[]
    records=[]
    for a in eligible:
        records.append({"성명":a.name,"학년":f"{a.grade}학년" if a.grade>0 else "미확인","_학년숫자":a.grade,
            "학제":f"{a.max_grade}년제","지역":a.region or "미확인",
            "전공":a.major or "미확인","이수학점":a.completed_credits,"졸업기준학점":a.graduation_credits,
            "이수율":round(a.completion_rate*100,1),"_이수율정렬":a.completion_rate,"GPA":a.gpa,
            "학년점수":a.grade_score,"이수율점수":a.completion_score,"가산점":a.bonus_score,"총점":a.total_score,
            "자격증어학":"✓" if a.bonus_cert else "","봉사50h":"✓" if a.bonus_volunteer else "",
            "자립확인서":"✓","재학증명서":"✓" if a.has_enrollment else "미확인","성적증명서":"✓" if a.has_transcript else "미확인",
            "비고":" | ".join(a.parse_notes) if a.parse_notes else "정상 처리"})
    records.sort(key=lambda r:(r["총점"],r["_이수율정렬"],r["_학년숫자"],r["GPA"]),reverse=True)
    all_list=[]
    for rank,rec in enumerate(records,1):
        rec["순위"]=rank; rec.pop("_학년숫자",None); rec.pop("_이수율정렬",None); all_list.append(rec)
    return all_list[:n], all_list

def build_report(selected: List[Dict], total: int) -> Dict[str,Any]:
    if not selected: return {}
    n=len(selected); scores=[r["총점"] for r in selected]; comp=[r["이수율"] for r in selected]; gpas=[r["GPA"] for r in selected]
    gd: Dict[str,int]={}
    for r in selected: gd[r["학년"]]=gd.get(r["학년"],0)+1
    rd: Dict[str,int]={}
    for r in selected: rd[r.get("지역","미확인")]=rd.get(r.get("지역","미확인"),0)+1
    cert=sum(1 for r in selected if r["자격증어학"]=="✓")
    vol =sum(1 for r in selected if r["봉사50h"]=="✓")
    return {"total_applicants":total,"selected_count":n,"selection_rate":round(n/total*100,1) if total else 0,
            "avg_score":round(sum(scores)/n,2),"max_score":round(max(scores),2),"min_score":round(min(scores),2),
            "avg_completion":round(sum(comp)/n,1),"avg_gpa":round(sum(gpas)/n,2),"grade_dist":gd,"region_dist":rd,
            "cert_count":cert,"vol_count":vol}

def make_demo_applicants(n: int=30) -> List[ApplicantData]:
    random.seed(42)
    names=["김민준","이서연","박도윤","최서현","정예은","강지호","조수아","윤민서","장하은","임준혁","오지원","한소율","신재현","권나연","유태양","배수빈","노현우","심지유","문성민","허다은","서지훈","안채원","남기태","고은서","류민호","전수현","양준서","설아린","마지현","제갈민"]
    majors=["컴퓨터공학과","전자공학과","기계공학과","국방학과","경영학과","사회복지학과","심리학과","소프트웨어학과","방위산업학과","화학공학과"]
    demo_regions=["서울","서울","서울","경기","경기","경기","인천","부산","대구","광주","대전","충남","충북","전북","전남","경북","경남","강원","울산","세종","제주","서울","경기","부산","대구","인천","경남","충남","전북","경북"]
    # 학제 구성: 4년제 22명, 3년제 5명, 2년제 3명
    demo_max_grades=[4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,3,3,3,3,3,2,2,2]
    results=[]
    for i in range(n):
        mg=demo_max_grades[i%len(demo_max_grades)]
        gc={4:random.choice([120.0,130.0,140.0]),3:random.choice([95.0,105.0]),2:random.choice([65.0,75.0])}[mg]
        a=ApplicantData(applicant_key=f"demo_{i}",name=names[i%len(names)],grade=random.randint(1,mg),
            max_grade=mg,major=majors[random.randint(0,len(majors)-1)],
            completed_credits=round(random.uniform(10,gc),1),graduation_credits=gc,
            gpa=round(random.uniform(1.5,4.3),2),has_certificate=random.random()>0.5,
            volunteer_hours=random.choice([0,20,55,80,100]),
            is_eligible=random.random()>0.1,has_enrollment=True,has_transcript=True,
            region=demo_regions[i%len(demo_regions)])
        ScoringEngine.calculate(a); results.append(a)
    return results

def _clean(obj: Any) -> Any:
    if isinstance(obj,float) and (math.isnan(obj) or math.isinf(obj)): return None
    if isinstance(obj,dict): return {k:_clean(v) for k,v in obj.items()}
    if isinstance(obj,list): return [_clean(v) for v in obj]
    return obj

# ──────────────────────────────────────────────────────────────────────
# API 엔드포인트
# ──────────────────────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
def upload_zip():
    _flush_log()
    if "file" not in request.files: return jsonify({"success":False,"error":"파일이 없습니다."}),400
    f=request.files["file"]
    if not f.filename.lower().endswith(".zip"): return jsonify({"success":False,"error":"ZIP 파일만 허용됩니다."}),400
    try:
        zb=f.read()
        if not zipfile.is_zipfile(io.BytesIO(zb)): return jsonify({"success":False,"error":"손상된 ZIP 파일입니다."}),400
        applics=DocumentProcessor().process(zb)
        if not applics: return jsonify({"success":False,"error":"처리 가능한 신청자가 없습니다."}),400
        try: excl=set(json.loads(request.form.get("excluded_names","[]")))
        except Exception: excl=set()
        sel,all_el=select_scholars(applics,MAX_SCHOLARS,excl)
        return jsonify(_clean({"success":True,"is_demo":False,"total_applicants":len(applics),"eligible_count":len(all_el),
            "selected_count":len(sel),"results":sel,"all_results":all_el,"stats":build_report(sel,len(applics)),
            "warnings":[{"name":a.name,"note":" | ".join(a.parse_notes)} for a in applics if a.parse_notes],
            "log":_flush_log()}))
    except MemoryError: return jsonify({"success":False,"error":"파일이 너무 큽니다."}),413
    except Exception as e: return jsonify({"success":False,"error":str(e)}),500

@app.route("/api/demo", methods=["POST"])
def demo():
    _flush_log()
    try:
        applics=make_demo_applicants(30)
        sel,all_el=select_scholars(applics,MAX_SCHOLARS)
        return jsonify(_clean({"success":True,"is_demo":True,"total_applicants":len(applics),"eligible_count":len(all_el),
            "selected_count":len(sel),"results":sel,"all_results":all_el,"stats":build_report(sel,len(applics)),
            "warnings":[],"log":_flush_log()}))
    except Exception as e: return jsonify({"success":False,"error":str(e)}),500

@app.route("/api/health")
def health():
    return jsonify({"status":"ok","timestamp":datetime.now().isoformat()})

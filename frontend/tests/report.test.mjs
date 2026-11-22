import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {reportMarkdown}=require('../.test-build/report.js');
test('postmortem export preserves unknown timing, simulation and literal evidence',()=>{
 const report={incident:{id:'closed-fixture',title:'[external](https://example.invalid) <script>bad()</script>',service:'catalog-service',status:'closed',analysis:{summary:'`not executable`'},audit:[{action:'closed'}],plan:{action:'restart'},execution_output:null,evidence_ids:['event:1']},mttd_seconds:null,mttr_seconds:null,incident_duration_seconds:5,timing_caveats:['onset unavailable'],lessons:['Confirm probable cause'],simulation:true};
 const result=reportMarkdown(report);
 assert.ok(result.includes('Fault-onset MTTD seconds: Not measured'));
 assert.ok(result.includes('Fault-onset MTTR seconds: Not measured'));
 assert.ok(result.includes('Incident duration seconds: 5'));
 assert.ok(result.includes('Simulation: true'));
 assert.ok(result.includes('event:1'));
 assert.ok(!result.includes('<script>'));
 assert.ok(!result.includes('[external]'));
 assert.ok(!result.includes('`not executable`'));
 assert.ok(result.includes('Generic follow-up checklist (not confirmed findings)'));
});

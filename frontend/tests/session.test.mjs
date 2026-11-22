import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {seal,unseal,validCsrf,consoleOrigin} from '../.test-build/session-codec.js';

test('session encryption, expiry, tamper rejection and CSRF',()=>{
 process.env.AEGIS_CONSOLE_SESSION_SECRET='ci-disposable-session-encryption-value';
 const encoded=seal('fixture-operator-token');
 assert.ok(!encoded.includes('fixture-operator-token'));
 const session=unseal(encoded);
 assert.equal(session.token,'fixture-operator-token');
 assert.equal(session.csrf.length,48);
 assert.equal(unseal(encoded.slice(0,-5)+'AAAAA'),null);
 assert.equal(unseal('not-a-session'),null);
 assert.equal(unseal('a'.repeat(2049)),null);
 assert.ok(validCsrf(session.csrf,session.csrf));
 assert.ok(!validCsrf(session.csrf,'wrong'));
 const now=Date.now;Date.now=()=>session.expires+1;
 try{assert.equal(unseal(encoded),null);}finally{Date.now=now;}
});
test('missing encryption secret fails closed',()=>{
 delete process.env.AEGIS_CONSOLE_SESSION_SECRET;
 assert.throws(()=>seal('fixture'));
 assert.equal(unseal('fixture'),null);
});
test('origin configuration rejects credentials and non-origin paths',()=>{
 process.env.AEGIS_CONSOLE_ORIGIN='https://console.example.invalid';
 assert.equal(consoleOrigin(),'https://console.example.invalid');
 for(const value of ['https://user:password@example.invalid','https://example.invalid/path','file:///tmp/test']){
  process.env.AEGIS_CONSOLE_ORIGIN=value;assert.throws(()=>consoleOrigin());
 }
 delete process.env.AEGIS_CONSOLE_ORIGIN;
});

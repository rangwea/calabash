"""Synthetic typed CRM. Uses only temporary tool-owned SQLite data in tests."""
import json

BACKEND = '''from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException

class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    stage: str = Field(default='New', max_length=40)

class Customer(CustomerInput):
    id: int

class FollowupInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str = Field(min_length=1, max_length=200)

class Followup(FollowupInput):
    id: int
    customer_id: int

class CustomerDetail(Customer):
    followups: list[Followup]

class Deleted(BaseModel):
    deleted: bool

def setup(app, sdk):
    database = sdk.data_dir / 'crm.sqlite'
    @contextmanager
    def connect():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, stage TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS followups (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), note TEXT NOT NULL)')

    @app.get('/api/customers', operation_id='list_customers', response_model=list[Customer])
    def list_customers(q: str = ''):
        with connect() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM customers WHERE name LIKE ? ORDER BY id', ('%' + q + '%',))]

    @app.post('/api/customers', operation_id='create_customer', response_model=Customer)
    def create_customer(payload: CustomerInput):
        with connect() as connection:
            cursor = connection.execute('INSERT INTO customers(name, stage) VALUES (?, ?)', (payload.name, payload.stage))
            return {'id': cursor.lastrowid, **payload.model_dump()}

    @app.put('/api/customers/{customer_id}', operation_id='edit_customer', response_model=Customer)
    def edit_customer(customer_id: int, payload: CustomerInput):
        with connect() as connection:
            cursor = connection.execute('UPDATE customers SET name=?, stage=? WHERE id=?', (payload.name, payload.stage, customer_id))
            if not cursor.rowcount:
                raise HTTPException(404, 'Customer missing')
            return {'id': customer_id, **payload.model_dump()}

    @app.get('/api/customers/{customer_id}', operation_id='customer_detail', response_model=CustomerDetail)
    def customer_detail(customer_id: int):
        with connect() as connection:
            row = connection.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
            if row is None:
                raise HTTPException(404, 'Customer missing')
            notes = [dict(item) for item in connection.execute('SELECT * FROM followups WHERE customer_id=? ORDER BY id', (customer_id,))]
            return {**dict(row), 'followups': notes}

    @app.post('/api/customers/{customer_id}/followups', operation_id='add_followup', response_model=Followup)
    def add_followup(customer_id: int, payload: FollowupInput):
        with connect() as connection:
            if not connection.execute('SELECT id FROM customers WHERE id=?', (customer_id,)).fetchone():
                raise HTTPException(404, 'Customer missing')
            cursor = connection.execute('INSERT INTO followups(customer_id, note) VALUES (?, ?)', (customer_id, payload.note))
            return {'id': cursor.lastrowid, 'customer_id': customer_id, **payload.model_dump()}

    @app.delete('/api/customers/{customer_id}', operation_id='delete_customer', response_model=Deleted)
    def delete_customer(customer_id: int):
        with connect() as connection:
            connection.execute('DELETE FROM followups WHERE customer_id=?', (customer_id,))
            connection.execute('DELETE FROM customers WHERE id=?', (customer_id,))
            return {'deleted': True}
'''

FRONTEND = '''<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type Customer, type CustomerDetail } from '@calabash/api'
const customers = ref<Customer[]>([])
const current = ref<CustomerDetail | null>(null)
const name = ref('')
const query = ref('')
const note = ref('')
const busy = ref(false)
const error = ref('')
async function perform(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await action() } catch (problem) { error.value = problem instanceof Error ? problem.message : 'Please retry' }
  finally { busy.value = false }
}
async function load() { customers.value = await api.list_customers({query: {q: query.value}}) }
async function select(id: number) { current.value = await api.customer_detail({params: {customer_id: id}}); name.value = current.value.name }
async function create() { const saved = await api.create_customer({body: {name: name.value}}); await load(); await select(saved.id) }
async function save() { if (!current.value) return; await api.edit_customer({params: {customer_id: current.value.id}, body: {name: name.value, stage: 'Contacted'}}); await load(); await select(current.value.id) }
async function followup() { if (!current.value) return; await api.add_followup({params: {customer_id: current.value.id}, body: {note: note.value}}); note.value = ''; await select(current.value.id) }
onMounted(() => perform(load))
</script>
<template>
<main class="crm"><header><h1>Customer workspace</h1><span>Local CRM · Synthetic acceptance</span></header>
<el-alert v-if="error" :title="error" type="error" :closable="false" />
<section class="toolbar"><el-input v-model="query" placeholder="Filter customers" /><el-button :loading="busy" @click="perform(load)">Search</el-button></section>
<el-table :data="customers" row-key="id" @row-click="row => perform(() => select(row.id))"><el-table-column prop="name" label="Customer" /><el-table-column prop="stage" label="Stage" /></el-table>
<el-empty v-if="!customers.length" description="Add your first customer" />
<section class="editor"><h2>{{ current ? 'Customer detail' : 'New customer' }}</h2>
<el-input v-model="name" placeholder="Customer name" /><el-button :disabled="busy || !name" @click="perform(create)">Add customer</el-button><el-button :disabled="busy || !current || !name" @click="perform(save)">Save changes</el-button>
<template v-if="current"><h3>Follow-ups</h3><ul><li v-for="item in current.followups" :key="item.id">{{ item.note }}</li></ul><el-input v-model="note" placeholder="Follow-up note" /><el-button :disabled="busy || !note" @click="perform(followup)">Add follow-up</el-button></template>
</section></main>
</template>
<style scoped>.crm{padding:24px;max-width:960px;margin:auto}header{display:flex;align-items:center;justify-content:space-between}header span{color:#687887}.toolbar{display:flex;gap:12px;margin:20px 0}.editor{padding:20px;border:1px solid #dfe6ed;border-radius:12px;margin-top:20px}.editor .el-input{max-width:300px;margin-right:12px}h1{font-size:22px}h2{font-size:18px}</style>
'''


def fixture():
    return {'tool.json': json.dumps({'format': 'calabash-vue-tool', 'version': 1, 'project': 'demo', 'name': 'crm_contract', 'title': 'Synthetic CRM'}),
            'backend/main.py': BACKEND, 'frontend/App.vue': FRONTEND}

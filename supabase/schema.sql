-- AgAI-33 Supabase Schema
-- Every column name is prefixed dispatch_ per project convention
-- (frontend will live at dispatch.datawebify.com)
-- Run this once against a fresh Supabase project (or a dedicated schema)
-- before starting the API locally.

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

create table dispatch_technicians (
    dispatch_technician_id text primary key,
    dispatch_technician_name text not null,
    dispatch_technician_phone text not null,
    dispatch_technician_skills text[] not null default '{}',
    dispatch_technician_status text not null default 'available',
    dispatch_technician_current_lat double precision,
    dispatch_technician_current_lng double precision,
    dispatch_technician_current_queue_depth integer not null default 0,
    dispatch_technician_shift_start text,
    dispatch_technician_shift_end text,
    dispatch_technician_created_at timestamptz not null default now(),
    dispatch_technician_updated_at timestamptz not null default now()
);

create table dispatch_technician_locations (
    dispatch_location_id uuid primary key default gen_random_uuid(),
    dispatch_technician_id text not null references dispatch_technicians(dispatch_technician_id),
    dispatch_location_lat double precision not null,
    dispatch_location_lng double precision not null,
    dispatch_location_updated_at timestamptz not null default now()
);

create table dispatch_jobs (
    dispatch_job_id uuid primary key default gen_random_uuid(),
    dispatch_session_id text not null,
    dispatch_customer_name text not null,
    dispatch_customer_phone text not null,
    dispatch_customer_email text,
    dispatch_job_type text not null,
    dispatch_customer_location text not null,
    dispatch_urgency text not null default 'routine',
    dispatch_assigned_technician_id text references dispatch_technicians(dispatch_technician_id),
    dispatch_assigned_technician_name text,
    dispatch_assigned_technician_phone text,
    dispatch_status text not null default 'pending',
    dispatch_notes text,
    dispatch_created_at timestamptz not null default now()
);

create table dispatch_sessions (
    dispatch_session_id text primary key,
    dispatch_channel text,
    dispatch_customer_phone text,
    dispatch_customer_email text,
    dispatch_customer_name text,
    dispatch_conversation_history jsonb not null default '[]',
    dispatch_current_intent text,
    dispatch_turn_count integer not null default 0,
    dispatch_is_active boolean not null default true,
    dispatch_updated_at timestamptz not null default now()
);

create table dispatch_agent_logs (
    dispatch_log_id uuid primary key default gen_random_uuid(),
    dispatch_session_id text not null,
    dispatch_event text not null,
    dispatch_channel text,
    dispatch_intent text,
    dispatch_job_id uuid,
    dispatch_metadata jsonb not null default '{}',
    dispatch_created_at timestamptz not null default now()
);

-- Indexes for the lookups the agents actually perform
create index idx_dispatch_jobs_customer_phone on dispatch_jobs(dispatch_customer_phone);
create index idx_dispatch_jobs_status on dispatch_jobs(dispatch_status);
create index idx_dispatch_technicians_status on dispatch_technicians(dispatch_technician_status);
create index idx_dispatch_technician_locations_tech_id on dispatch_technician_locations(dispatch_technician_id, dispatch_location_updated_at desc);

-- Sample seed data for local testing (safe to delete before going live)
insert into dispatch_technicians (
    dispatch_technician_id, dispatch_technician_name, dispatch_technician_phone,
    dispatch_technician_skills, dispatch_technician_status,
    dispatch_technician_current_lat, dispatch_technician_current_lng,
    dispatch_technician_current_queue_depth, dispatch_technician_shift_start, dispatch_technician_shift_end
) values
    ('tech_001', 'Carlos Mendes', '+15551234001', array['hvac', 'electrical'], 'available', 33.4484, -112.0740, 0, '08:00', '17:00'),
    ('tech_002', 'Dana Whitfield', '+15551234002', array['plumbing', 'general'], 'available', 33.5100, -112.0500, 1, '08:00', '17:00'),
    ('tech_003', 'Jorge Alvarez', '+15551234003', array['hvac', 'security_alarm'], 'available', 33.3900, -111.9900, 2, '09:00', '18:00');

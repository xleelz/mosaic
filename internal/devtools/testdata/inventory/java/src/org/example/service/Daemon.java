package org.example.service;

public class Daemon
{
    public static void main(String args[])
    {
        new Daemon();
    }

    static class Helper
    {
        public void main(String[] args) { } // not static: not an entry point
    }
}

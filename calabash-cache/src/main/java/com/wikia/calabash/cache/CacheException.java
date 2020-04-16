package com.wikia.calabash.cache;

import java.lang.reflect.Method;

public class CacheException extends RuntimeException {
    public CacheException(String cacheName, String cacheKey, Method method, Throwable throwable) {
        super(message(cacheName, cacheKey, method), throwable);
    }

    public static String message(String cacheName, String cacheKey, Method method) {
        return String.format("cacheName={};cacheKey={};method={}", cacheName, cacheKey, method);
    }
}

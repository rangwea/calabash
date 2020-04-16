package com.wikia.calabash.cache.guava;

import com.google.common.cache.CacheBuilder;
import com.google.common.cache.CacheLoader;
import com.google.common.cache.LoadingCache;
import com.google.common.util.concurrent.ListenableFuture;
import com.google.common.util.concurrent.ListeningExecutorService;
import com.wikia.calabash.cache.Cache;
import com.wikia.calabash.cache.CacheException;
import com.wikia.calabash.cache.JsonKeyParser;
import com.wikia.calabash.cache.KeyParser;
import lombok.extern.slf4j.Slf4j;

import java.lang.reflect.Method;
import java.util.Optional;

@Slf4j
public class LocalCache implements Cache {
    private final LoadingCache<String, Optional<Object>> guavaCache;
    private final ListeningExecutorService refreshListeningExecutor;

    private final LocalCached localCached;
    private final KeyParser keyParser = new JsonKeyParser();
    private final Method cachedMethod;

    public LocalCache(ListeningExecutorService refreshListeningExecutor, LocalCached localCached, Method cacheMethod, Object methodProxy) {
        this.refreshListeningExecutor = refreshListeningExecutor;
        this.localCached = localCached;
        this.cachedMethod = cacheMethod;
        this.guavaCache = buildCache(localCached, cacheMethod, methodProxy);
    }

    public Object get(Object[] args) {
        try {
            String cacheKey = keyParser.generateKey(localCached.name(), localCached.key(), cachedMethod, args);
            Optional<Object> optional = guavaCache.get(cacheKey);
            return optional.orElse(null);
        } catch (Throwable throwable) {
            throw new CacheException(localCached.name(), localCached.key(), cachedMethod, throwable);
        }
    }

    public void put(Object[] args, Object obj) {
        try {
            String key = keyParser.generateKey(localCached.name(), localCached.key(), this.cachedMethod, args);
            this.put(key, Optional.ofNullable(obj));
        } catch (Throwable throwable) {
            throw new CacheException(localCached.name(), localCached.key(), cachedMethod, throwable);
        }
    }

    private void put(String key, Object obj) {
        guavaCache.put(key, Optional.ofNullable(obj));
    }

    @SuppressWarnings("unchecked")
    private LoadingCache<String, Optional<Object>> buildCache(LocalCached localCache, Method method, Object methodProxy) {
        CacheBuilder cacheBuilder = CacheBuilder.newBuilder();

        if (localCache.expireAfterWrite() != 0) {
            cacheBuilder.expireAfterWrite(localCache.expireAfterWrite(), localCache.expireTimeUnit());
        }
        if (localCache.refreshAfterWrite() != 0) {
            cacheBuilder.refreshAfterWrite(localCache.refreshAfterWrite(), localCache.refreshTimeUnit());
        }

        cacheBuilder.maximumSize(localCache.maximumSize());

        return cacheBuilder.build(new CacheLoader<String, Object>() {
            @Override
            public Object load(String key) {
                try {
                    Object[] args = keyParser.parseKey(key, method);
                    Object proceed = method.invoke(methodProxy, args);
                    if (log.isDebugEnabled()) {
                        log.debug("load cache:key={}, value={}", key, proceed);
                    } else {
                        log.info("load cache:key={}", key);
                    }

                    if (proceed == null && !localCache.cacheNullValue()) {
                        return null;
                    }
                    return Optional.ofNullable(proceed);
                } catch (Throwable throwable) {
                    throw new RuntimeException(String.format("guava load cache fail:key=%s", key), throwable);
                }
            }

            @Override
            public ListenableFuture<Object> reload(String key, Object oldValue) throws Exception {
                return refreshListeningExecutor.submit(() -> load(key));
            }
        });
    }
}

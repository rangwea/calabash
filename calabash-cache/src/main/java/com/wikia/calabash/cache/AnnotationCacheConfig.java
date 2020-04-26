package com.wikia.calabash.cache;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * @author feijianwu(feijianwu @ tencent.com)
 * @since 2020/4/24 16:44
 */
@Data
@Configuration
@ConfigurationProperties(prefix = "annotation.cache")
public class AnnotationCacheConfig {
    private boolean enable = true;
}
